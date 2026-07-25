from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.employee import Employee


def get_by_id(db: Session, employee_id: UUID) -> Employee | None:
    return db.scalar(
        select(Employee)
        .options(joinedload(Employee.department), joinedload(Employee.manager))
        .where(Employee.id == employee_id)
    )


def get_by_work_email(db: Session, work_email: str) -> Employee | None:
    return db.scalar(select(Employee).where(Employee.work_email == work_email))


def list_all(db: Session) -> list[Employee]:
    return list(
        db.scalars(
            select(Employee)
            .options(joinedload(Employee.department), joinedload(Employee.manager))
            .order_by(Employee.last_name, Employee.first_name)
        )
        .unique()
        .all()
    )


def create(db: Session, **fields: Any) -> Employee:
    employee = Employee(**fields)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def update(db: Session, employee: Employee, **fields: Any) -> Employee:
    for key, value in fields.items():
        if value is not None:
            setattr(employee, key, value)
    db.commit()
    db.refresh(employee)
    return employee
