from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTokenError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import user_repo

# HTTPBearer (not OAuth2PasswordBearer) on purpose: this is plain JWT bearer
# auth, not spec-compliant OAuth2. HTTPBearer also lets you paste a raw token
# into Swagger's "Authorize" dialog, which OAuth2PasswordBearer's form-based
# flow doesn't support for a JSON-body /auth/login endpoint.
bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)  # raises InvalidTokenError on failure
    user = user_repo.get_by_id(db, payload.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("User not found or inactive")
    return user


def require_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: `Depends(require_role(UserRole.ADMINISTRATOR))`.

    Enforced server-side, not just hidden in the frontend — see
    docs/architecture/authentication.md.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise PermissionDeniedError(
                f"Requires one of roles: {', '.join(r.value for r in allowed_roles)}"
            )
        return current_user

    return dependency
