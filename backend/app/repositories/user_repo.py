from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ExternalEntityType, ProviderType, UserRole
from app.models.organization import ExternalIdentity
from app.models.user import User


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def get_by_email_ci(db: Session, email: str) -> User | None:
    """Case-insensitive email lookup.

    Needed by SCIM and by OIDC login, where the address arrives from an
    external system that may normalize case differently than we stored it.
    `Dana.Whitfield@cordant.io` and `dana.whitfield@cordant.io` are the same
    mailbox everywhere that matters, and treating them as different accounts
    is how a directory ends up with duplicates that are painful to merge.
    """
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def get_by_external_id(
    db: Session, *, system: ProviderType, external_id: str
) -> User | None:
    """Resolve a user through its identity in an external system.

    Authoritative for OIDC login and SCIM, because it survives an email
    change in the upstream directory — which is exactly the event that
    breaks any email-keyed integration.
    """
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.system == system,
            ExternalIdentity.entity_type == ExternalEntityType.USER,
            ExternalIdentity.external_id == external_id,
        )
    )
    if identity is None:
        return None
    return db.get(User, identity.entity_id)


def get_by_id(db: Session, user_id: UUID) -> User | None:
    return db.get(User, user_id)


def get_by_employee_id(db: Session, employee_id: UUID) -> User | None:
    """Resolves an Employee row to its linked login, if one exists — used
    by the workflow engine (Phase 7) to find the specific user a
    manager_approval should be assigned to. Not every Employee has a User
    account (see Employee's own docstring), so this can legitimately return
    None even for a real manager."""
    return db.scalar(select(User).where(User.employee_id == employee_id))


def list_all(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)))


def list_by_role(db: Session, role: UserRole) -> list[User]:
    """Used for role-pool approval notifications (IT, Security — see
    workflows/service.py's _create_approver / _create_approval_request):
    there's no single assigned_user_id for these roles, so notifying "the
    approver" means notifying everyone who holds the role instead of one
    resolved person."""
    return list(db.scalars(select(User).where(User.role == role).order_by(User.created_at)))


def create(
    db: Session, *, email: str, hashed_password: str, full_name: str, role: UserRole
) -> User:
    user = User(email=email, hashed_password=hashed_password, full_name=full_name, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
