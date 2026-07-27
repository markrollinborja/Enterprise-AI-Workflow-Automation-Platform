from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application


def get_by_id(db: Session, application_id: UUID) -> Application | None:
    return db.get(Application, application_id)


def get_by_name(db: Session, name: str) -> Application | None:
    return db.scalar(select(Application).where(Application.name == name))


def list_all(db: Session) -> list[Application]:
    return list(db.scalars(select(Application).order_by(Application.name)))


def create(db: Session, **fields: Any) -> Application:
    application = Application(**fields)
    db.add(application)
    db.commit()
    db.refresh(application)
    return application
