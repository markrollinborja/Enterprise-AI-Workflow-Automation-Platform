from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.department import Department


def get_by_id(db: Session, department_id: UUID) -> Department | None:
    return db.get(Department, department_id)


def get_by_name(db: Session, name: str) -> Department | None:
    return db.scalar(select(Department).where(Department.name == name))


def list_all(db: Session) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.name)))


def create(db: Session, *, name: str) -> Department:
    department = Department(name=name)
    db.add(department)
    db.commit()
    db.refresh(department)
    return department
