from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowEvent


def get_by_dedup_key(db: Session, dedup_key: str) -> WorkflowEvent | None:
    return db.scalar(select(WorkflowEvent).where(WorkflowEvent.dedup_key == dedup_key))


def create(db: Session, **fields: Any) -> WorkflowEvent:
    event = WorkflowEvent(**fields)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
