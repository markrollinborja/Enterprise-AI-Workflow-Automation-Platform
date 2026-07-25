"""Same minimal scope as workflow_instance_repo.py — real usage (creating a
full set of step rows in definition order, advancing them) is Phase 6."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workflow import WorkflowStepInstance


def get_by_id(db: Session, step_instance_id: UUID) -> WorkflowStepInstance | None:
    return db.get(WorkflowStepInstance, step_instance_id)


def list_for_instance(db: Session, workflow_instance_id: UUID) -> list[WorkflowStepInstance]:
    return list(
        db.scalars(
            select(WorkflowStepInstance)
            .where(WorkflowStepInstance.workflow_instance_id == workflow_instance_id)
            .order_by(WorkflowStepInstance.created_at)
        )
    )


def create(db: Session, **fields: Any) -> WorkflowStepInstance:
    step = WorkflowStepInstance(**fields)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step
