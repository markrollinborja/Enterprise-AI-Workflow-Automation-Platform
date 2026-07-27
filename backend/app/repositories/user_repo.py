from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.user import User


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


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


def create(
    db: Session, *, email: str, hashed_password: str, full_name: str, role: UserRole
) -> User:
    user = User(email=email, hashed_password=hashed_password, full_name=full_name, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
