"""Turning a verified OIDC principal into a local User row.

Two jobs: map Keycloak roles onto this application's six roles, and resolve
the token's subject to a `User`.

**OIDC authenticates; SCIM provisions.** A token for a user this platform has
never heard of is rejected, not silently turned into a new account. That is
the deliberate line between Module 4 and Module 5: just-in-time provisioning
on login would mean anyone Keycloak trusts becomes a Meridian user with
whatever role their token claims, bypassing the provisioning path entirely
and making SCIM decorative. It also removes any audit trail for account
creation — "who created this user?" would answer "they logged in once".

The cost is that a Keycloak user must be provisioned before they can sign in,
which is exactly how a real SCIM-backed deployment behaves.
"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTokenError, PermissionDeniedError
from app.core.oidc import OIDCPrincipal
from app.models.enums import ExternalEntityType, ProviderType, UserRole
from app.models.user import User
from app.repositories import organization_repo, user_repo

logger = logging.getLogger(__name__)

# Keycloak role name -> Meridian role. Prefixed in the realm to avoid
# colliding with Keycloak's own built-ins (`offline_access`,
# `default-roles-*`, `uma_authorization`), which every user carries and none
# of which mean anything here. An unprefixed role called "admin" in a shared
# realm would be ambiguous about *which* application's admin it meant.
ROLE_PREFIX = "meridian-"

_ROLE_MAP: dict[str, UserRole] = {
    f"{ROLE_PREFIX}employee": UserRole.EMPLOYEE,
    f"{ROLE_PREFIX}manager": UserRole.MANAGER,
    f"{ROLE_PREFIX}hr": UserRole.HR,
    f"{ROLE_PREFIX}it": UserRole.IT,
    f"{ROLE_PREFIX}security": UserRole.SECURITY,
    f"{ROLE_PREFIX}administrator": UserRole.ADMINISTRATOR,
}

# Least-privilege ordering, lowest first. When a token carries several
# mapped roles, the *highest* wins — a user who is both manager and
# administrator should get administrator, not whichever happened to be
# first in an unordered set from the token.
_ROLE_PRECEDENCE: tuple[UserRole, ...] = (
    UserRole.EMPLOYEE,
    UserRole.MANAGER,
    UserRole.HR,
    UserRole.IT,
    UserRole.SECURITY,
    UserRole.ADMINISTRATOR,
)


def map_roles(principal: OIDCPrincipal) -> UserRole | None:
    """Highest-precedence Meridian role in the token, or None if there is none.

    Returning None rather than defaulting to EMPLOYEE is the safer failure:
    a misconfigured role mapper would otherwise silently grant every
    Keycloak user in the realm a working Meridian account.
    """
    claimed = set(principal.realm_roles) | set(principal.client_roles)
    mapped = {_ROLE_MAP[name] for name in claimed if name in _ROLE_MAP}
    if not mapped:
        return None
    return max(mapped, key=_ROLE_PRECEDENCE.index)


def resolve_user(db: Session, principal: OIDCPrincipal) -> User:
    """Find the local User this token refers to.

    Resolution order matters. The external-identity mapping is authoritative
    because it survives an email change in Keycloak; email is a fallback for
    the first login of a user who was seeded or SCIM-provisioned before any
    mapping existed, and that first successful match writes the mapping so
    subsequent logins take the stable path.
    """
    user = user_repo.get_by_external_id(
        db, system=ProviderType.KEYCLOAK, external_id=principal.subject
    )

    if user is None and principal.email:
        # Case-insensitive: Keycloak may normalize the address differently
        # than we stored it, and treating those as different accounts is how
        # a directory acquires duplicates nobody wants to merge later.
        user = user_repo.get_by_email_ci(db, principal.email)
        if user is not None:
            organization_repo.link_external_identity(
                db,
                entity_id=user.id,
                entity_type=ExternalEntityType.USER,
                system=ProviderType.KEYCLOAK,
                external_id=principal.subject,
            )
            logger.info(
                "Linked Keycloak subject to existing user",
                extra={"user_id": str(user.id), "auth_mode": "oidc"},
            )

    if user is None:
        # Not 404 and not "account created" — an authenticated stranger.
        # Logged with the subject, never the email, so an unprovisioned
        # login attempt is investigable without writing an unknown person's
        # address into our logs.
        logger.warning(
            "OIDC token for an unprovisioned user rejected",
            extra={"oidc_subject": principal.subject},
        )
        raise InvalidTokenError("No Meridian account is provisioned for this identity")

    if not user.is_active:
        # Deactivation is enforced here as well as in Keycloak. A token
        # issued minutes before deprovisioning is still cryptographically
        # valid until it expires, so the identity provider alone cannot
        # revoke access promptly — the resource server has to check too.
        raise PermissionDeniedError("This account is deactivated")

    return user
