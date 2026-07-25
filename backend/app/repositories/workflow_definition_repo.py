from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowDefinition


def get_by_id(db: Session, definition_id: UUID) -> WorkflowDefinition | None:
    return db.get(WorkflowDefinition, definition_id)


def get_active_by_key(db: Session, key: str) -> WorkflowDefinition | None:
    return db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.key == key, WorkflowDefinition.is_active.is_(True)
        )
    )


def list_active(db: Session) -> list[WorkflowDefinition]:
    return list(
        db.scalars(
            select(WorkflowDefinition)
            .where(WorkflowDefinition.is_active.is_(True))
            .order_by(WorkflowDefinition.name)
        )
    )


def create(db: Session, **fields: Any) -> WorkflowDefinition:
    definition = WorkflowDefinition(**fields)
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


def deactivate(db: Session, definition: WorkflowDefinition) -> None:
    """Used by the loader when a newer version of the same key is being
    inserted — see WorkflowDefinition's docstring on why "one active row per
    key" is enforced here, at the application layer, rather than a DB
    constraint."""
    definition.is_active = False
    db.add(definition)
    db.commit()
