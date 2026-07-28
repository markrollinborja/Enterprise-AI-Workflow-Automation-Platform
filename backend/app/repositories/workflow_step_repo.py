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


def get_by_external_ref(db: Session, external_ref: str) -> WorkflowStepInstance | None:
    """What api/routes/webhooks.py looks a step up by — external_ref isn't
    unique at the DB level (see the column's own comment), so this returns
    the most recently created match. In practice a collision only matters
    if two *currently open* WAITING_EXTERNAL steps ever shared a key, which
    mock mode's low-collision-probability key generator makes exceedingly
    unlikely at this project's demo scale, and real Jira Cloud keys are
    genuinely unique — not worth a more defensive query for V1."""
    return db.scalars(
        select(WorkflowStepInstance)
        .where(WorkflowStepInstance.external_ref == external_ref)
        .order_by(WorkflowStepInstance.created_at.desc())
        .limit(1)
    ).first()


def create(db: Session, **fields: Any) -> WorkflowStepInstance:
    step = WorkflowStepInstance(**fields)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step
