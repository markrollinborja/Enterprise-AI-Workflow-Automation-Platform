"""Request-scoped dependencies: who is calling, and may they do this.

`get_current_user` is the convergence point ADR-0015 promised. Two entirely
different authentication mechanisms — a self-issued HS256 JWT and a Keycloak
RS256 access token validated against JWKS — resolve here to the same `User`
row. Everything downstream (`require_role`, every route, every service) is
written once and cannot tell which mode produced the user.

That property is the whole justification for dual-mode auth, and it is not
self-maintaining. `tests/test_auth_modes.py` runs the same RBAC assertions
through both modes and requires identical decisions; if the two paths ever
diverge on authorization, that test is what catches it rather than a
production incident.
"""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth_mode import AuthMode, resolve_auth_mode
from app.core.config import get_settings
from app.core.exceptions import AppError, InvalidTokenError, PermissionDeniedError
from app.core.oidc import OIDCUnavailableError, OIDCValidator
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import user_repo
from app.services.auth import oidc_resolver

# HTTPBearer (not OAuth2PasswordBearer) on purpose: this is plain JWT bearer
# auth, not spec-compliant OAuth2. HTTPBearer also lets you paste a raw token
# into Swagger's "Authorize" dialog, which OAuth2PasswordBearer's form-based
# flow doesn't support for a JSON-body /auth/login endpoint.
bearer_scheme = HTTPBearer(auto_error=True)


class IdentityProviderUnavailableError(AppError):
    """Keycloak could not be reached to verify a token.

    503, not 401. The caller's token may be perfectly valid — telling them
    it is invalid sends people to reset credentials that were never the
    problem, and hides an outage behind a wall of authentication failures.
    """

    status_code = 503


# Built once rather than per request: the validator owns the JWKS cache, and
# a fresh instance per request would refetch Keycloak's signing keys on every
# authenticated call. Created lazily so that `AUTH_MODE=local` never
# constructs one, which is what keeps the test suite free of any Keycloak
# dependency.
_oidc_validator: OIDCValidator | None = None


def get_oidc_validator() -> OIDCValidator:
    global _oidc_validator
    if _oidc_validator is None:
        _oidc_validator = OIDCValidator(get_settings())
    return _oidc_validator


def reset_oidc_validator() -> None:
    """Drop the cached validator. For tests that change OIDC settings."""
    global _oidc_validator
    _oidc_validator = None


def _current_user_local(token: str, db: Session) -> User:
    payload = decode_access_token(token)  # raises InvalidTokenError on failure
    user = user_repo.get_by_id(db, payload.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("User not found or inactive")
    return user


def _current_user_oidc(token: str, db: Session) -> User:
    try:
        principal = get_oidc_validator().validate(token)
    except OIDCUnavailableError as exc:
        raise IdentityProviderUnavailableError(
            "Identity provider is unavailable; try again shortly"
        ) from exc

    user = oidc_resolver.resolve_user(db, principal)

    # The token's roles are authoritative, not the local row's. Keycloak is
    # the source of truth for authorization in this mode, so a role revoked
    # there must take effect on the next request rather than whenever
    # someone remembers to update the database. The local row still governs
    # *whether* the account exists and is active.
    mapped_role = oidc_resolver.map_roles(principal)
    if mapped_role is None:
        raise PermissionDeniedError("This identity carries no Meridian role")
    if user.role != mapped_role:
        user.role = mapped_role
        db.commit()

    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """The authenticated user, whichever mode this deployment runs in."""
    mode = resolve_auth_mode(get_settings())
    token = credentials.credentials

    if mode is AuthMode.OIDC:
        return _current_user_oidc(token, db)
    return _current_user_local(token, db)


def require_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: `Depends(require_role(UserRole.ADMINISTRATOR))`.

    Enforced server-side, not just hidden in the frontend — see
    docs/architecture/authentication.md. Unchanged by dual-mode auth, and
    deliberately so: authorization is written once and receives the same
    `User` regardless of how that user was authenticated.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise PermissionDeniedError(
                f"Requires one of roles: {', '.join(r.value for r in allowed_roles)}"
            )
        return current_user

    return dependency
