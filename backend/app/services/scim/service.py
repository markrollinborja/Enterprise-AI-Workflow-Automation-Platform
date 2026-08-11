"""SCIM provisioning service — the write path for user lifecycle.

This is where "OIDC authenticates, SCIM provisions" becomes real: everything
that creates, updates, or deactivates a Meridian account for an external
identity goes through here, so account lifecycle has exactly one code path
and one audit trail.

Deactivation, never deletion. `DELETE /Users/{id}` is deliberately not
implemented and `active: false` is the only way an account goes away.
Deleting a user would orphan every approval they gave, every workflow they
started, and every audit row naming them — which is precisely the history you
need when investigating what a departed employee had access to. Soft
deactivation keeps the record and removes the access, and it is what a real
deprovisioning integration should do.
"""

import logging
import secrets
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.security import hash_password
from app.models.enums import ExternalEntityType, ProviderType, UserRole
from app.models.user import User
from app.repositories import organization_repo, user_repo
from app.schemas.scim import ScimPatchRequest, ScimUserRequest
from app.services.auth.oidc_resolver import ROLE_PREFIX

logger = logging.getLogger(__name__)

# Role assigned when a client provisions a user without specifying one.
# EMPLOYEE, the least-privileged role: an integration bug that drops the
# role attribute should under-grant, never over-grant.
DEFAULT_PROVISIONED_ROLE = UserRole.EMPLOYEE


class ScimConflictError(AppError):
    """A user with this userName already exists.

    409 with scimType "uniqueness" — the signal that tells a client to fetch
    the existing resource rather than retry the create forever.
    """

    status_code = 409


class ScimInvalidValueError(AppError):
    status_code = 400


def _role_from_scim(roles: list[str]) -> UserRole:
    """Map SCIM `roles` onto a Meridian role.

    Accepts both the prefixed form used in Keycloak ("meridian-hr") and the
    bare value ("hr"), because a SCIM client's role catalog is configured by
    whoever set up the connector and expecting one exact spelling is how
    provisioning silently assigns everyone the default.
    """
    for raw in roles:
        candidate = raw.strip().lower()
        candidate = candidate.removeprefix(ROLE_PREFIX)
        try:
            return UserRole(candidate)
        except ValueError:
            continue
    return DEFAULT_PROVISIONED_ROLE


def create_user(db: Session, payload: ScimUserRequest) -> User:
    """Provision a user. Idempotent on externalId.

    A client re-sending a create for a user it already provisioned gets the
    existing user back rather than a 409. That is the behavior real
    connectors depend on after a retry or a full re-sync — treating it as a
    conflict makes every re-sync look like a failure. A *different* user
    claiming an existing userName is a genuine conflict and does get 409.
    """
    if payload.external_id:
        existing = user_repo.get_by_external_id(
            db, system=ProviderType.SCIM_CLIENT, external_id=payload.external_id
        )
        if existing is not None:
            logger.info(
                "SCIM create matched an existing provisioned user",
                extra={"user_id": str(existing.id), "scim_external_id": payload.external_id},
            )
            return existing

    email = payload.primary_email()
    if not email:
        raise ScimInvalidValueError("A user must carry an email address or an email userName")

    if user_repo.get_by_email_ci(db, email) is not None:
        raise ScimConflictError(f"A user with userName '{payload.user_name}' already exists")

    user = User(
        email=email,
        # A provisioned user authenticates through the identity provider, not
        # against this hash — but the column is NOT NULL and a predictable
        # placeholder would be a password. Random and immediately discarded:
        # nobody, including us, knows it.
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        full_name=_full_name(payload),
        role=_role_from_scim(payload.roles),
        is_active=payload.active,
    )
    db.add(user)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        # Lost a race with a concurrent create for the same address. The
        # unique constraint is the arbiter; this converts it into the
        # protocol's own conflict rather than a 500.
        raise ScimConflictError(
            f"A user with userName '{payload.user_name}' already exists"
        ) from exc

    if payload.external_id:
        organization_repo.link_external_identity(
            db,
            entity_id=user.id,
            entity_type=ExternalEntityType.USER,
            system=ProviderType.SCIM_CLIENT,
            external_id=payload.external_id,
        )
    else:
        db.commit()

    db.refresh(user)
    logger.info(
        "SCIM provisioned a user",
        extra={
            "user_id": str(user.id),
            "role": user.role.value,
            "scim_external_id": payload.external_id,
        },
    )
    return user


def get_user(db: Session, user_id: UUID) -> User:
    user = user_repo.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


def find_by_username(db: Session, user_name: str) -> User | None:
    return user_repo.get_by_email_ci(db, user_name)


def apply_patch(db: Session, user: User, patch: ScimPatchRequest) -> User:
    """Apply a SCIM PATCH.

    Supports the operations connectors actually send for user lifecycle:
    replacing `active` (the deprovisioning signal), `name`, and `roles`.
    Anything else is rejected with `invalidPath` rather than silently
    ignored — a client that believes it disabled an account when nothing
    happened is a security problem, not a compatibility one.
    """
    changed: list[str] = []

    for operation in patch.operations:
        op = operation.op.strip().lower()
        if op not in {"replace", "add"}:
            raise ScimInvalidValueError(f"Unsupported PATCH operation: {operation.op}")

        # Two shapes are legal: a targeted op with `path`, and an untargeted
        # one whose `value` is a dict of attributes. Keycloak sends the
        # second; Okta sends the first. Both must work.
        if operation.path:
            updates = {operation.path: operation.value}
        elif isinstance(operation.value, dict):
            updates = operation.value
        else:
            raise ScimInvalidValueError("PATCH operation must carry a path or an object value")

        for raw_path, value in updates.items():
            attribute = raw_path.strip().lower()
            if attribute == "active":
                user.is_active = _as_bool(value)
                changed.append("active")
            elif attribute in {"name", "name.formatted", "displayname"}:
                user.full_name = _name_value(value) or user.full_name
                changed.append("name")
            elif attribute == "roles":
                user.role = _role_from_scim(_as_role_list(value))
                changed.append("roles")
            elif attribute in {"username", "emails", "emails[type eq \"work\"].value"}:
                new_email = _email_value(value)
                if new_email:
                    user.email = new_email
                    changed.append("email")
            else:
                raise ScimInvalidValueError(f"Unsupported PATCH path: {raw_path}")

    db.commit()
    db.refresh(user)
    logger.info(
        "SCIM patched a user",
        extra={"user_id": str(user.id), "attributes": changed, "active": user.is_active},
    )
    return user


def deactivate_user(db: Session, user: User) -> User:
    """Deprovision. Soft, never a delete — see the module docstring."""
    user.is_active = False
    db.commit()
    db.refresh(user)
    logger.info("SCIM deactivated a user", extra={"user_id": str(user.id)})
    return user


def _full_name(payload: ScimUserRequest) -> str:
    if payload.name:
        if payload.name.formatted:
            return payload.name.formatted
        parts = [payload.name.given_name, payload.name.family_name]
        joined = " ".join(p for p in parts if p)
        if joined:
            return joined
    return payload.user_name


def _as_bool(value: object) -> bool:
    """Coerce SCIM's several spellings of false.

    Clients send `false`, `"false"`, and `"False"` for the same intent.
    Guessing wrong here means an account the directory believes is disabled
    stays enabled — the worst possible direction to be lenient in, which is
    why anything unrecognised raises instead of defaulting.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
    raise ScimInvalidValueError(f"Expected a boolean for 'active', got {value!r}")


def _name_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        formatted = value.get("formatted")
        if isinstance(formatted, str):
            return formatted
        parts = [value.get("givenName"), value.get("familyName")]
        joined = " ".join(str(p) for p in parts if p)
        return joined or None
    return None


def _as_role_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and isinstance(item.get("value"), str):
                result.append(item["value"])
        return result
    return []


def _email_value(value: object) -> str | None:
    if isinstance(value, str):
        return value if "@" in value else None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                return item["value"]
    if isinstance(value, dict) and isinstance(value.get("value"), str):
        return value["value"]
    return None
