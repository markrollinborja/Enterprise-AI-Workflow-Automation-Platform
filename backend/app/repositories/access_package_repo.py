from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.access_package import AccessPackage


def get_by_id(db: Session, access_package_id: UUID) -> AccessPackage | None:
    return db.get(AccessPackage, access_package_id)


def get_by_name(db: Session, name: str) -> AccessPackage | None:
    return db.scalar(select(AccessPackage).where(AccessPackage.name == name))


def list_all(db: Session) -> list[AccessPackage]:
    return list(db.scalars(select(AccessPackage).order_by(AccessPackage.name)))


def create(db: Session, **fields: Any) -> AccessPackage:
    access_package = AccessPackage(**fields)
    db.add(access_package)
    db.commit()
    db.refresh(access_package)
    return access_package
