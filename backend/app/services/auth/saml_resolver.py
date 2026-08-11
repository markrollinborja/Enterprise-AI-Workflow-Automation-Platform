"""Turning a verified SAML principal into a local User row.

Deliberately the thinnest version of what oidc_resolver.py does. The SAML
PoC route is never AUTH_MODE's dispatch target (ADR-0021) — a token it
issues only works because it happens to be the same local-JWT format
AUTH_MODE=local already accepts, not because SAML is a second production
sign-in path with its own role-mapping and external-identity-linking
machinery to keep in sync with OIDC's. Building that machinery for an
endpoint nothing routes users to by default would be exactly the kind of
scaffolding-with-no-second-caller this project's principles warn against.

**SAML authenticates; SCIM provisions**, same line OIDC draws. A NameID this
platform has never heard of is rejected, not silently turned into a new
account — no just-in-time provisioning here either.
"""

import logging

from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTokenError, PermissionDeniedError
from app.core.saml import SAMLPrincipal
from app.models.user import User
from app.repositories import user_repo

logger = logging.getLogger(__name__)


def resolve_user(db: Session, principal: SAMLPrincipal) -> User:
    """Find the local User this assertion's NameID refers to.

    Case-insensitive, same reasoning as oidc_resolver's email fallback:
    Keycloak may normalize the address differently than it is stored here,
    and treating those as different accounts is how a directory acquires
    duplicates nobody merges later.
    """
    user = user_repo.get_by_email_ci(db, principal.name_id)

    if user is None:
        # Logged with the NameID, not framed as "email" — this endpoint
        # never confirmed the value is actually reachable, only that
        # Keycloak's signature vouches for it as this assertion's subject.
        logger.warning(
            "SAML assertion for an unprovisioned identity rejected",
            extra={"saml_name_id": principal.name_id},
        )
        raise InvalidTokenError("No Meridian account is provisioned for this identity")

    if not user.is_active:
        raise PermissionDeniedError("This account is deactivated")

    return user
