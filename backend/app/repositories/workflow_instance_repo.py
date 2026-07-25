"""Minimal on purpose — Phase 5 only needs enough to support tests and the
definition loader. `start_workflow` and friends (filtering by status,
resuming, etc.) land in Phase 6 once there's an engine calling them."""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowInstance


def get_by_id(db: Session, instance_id: UUID) -> WorkflowInstance | None:
    return db.get(WorkflowInstance, instance_id)


def create(db: Session, **fields: Any) -> WorkflowInstance:
    instance = WorkflowInstance(**fields)
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance
