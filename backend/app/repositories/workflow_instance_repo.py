"""Phase 6 adds list_ready_to_advance for the worker — everything else was
already enough for the engine (start_workflow/advance_workflow just need
get_by_id/create)."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import InstanceStatus, StepStatus
from app.models.workflow import WorkflowInstance, WorkflowStepInstance


def get_by_id(db: Session, instance_id: UUID) -> WorkflowInstance | None:
    return db.get(WorkflowInstance, instance_id)


def create(db: Session, **fields: Any) -> WorkflowInstance:
    instance = WorkflowInstance(**fields)
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


def list_ready_to_advance(db: Session) -> list[WorkflowInstance]:
    """What the worker polls: instances that are `running` (started but not
    yet advanced to their next pause/completion — normally handled inline
    by start_workflow/resume_workflow_step, but a fallback here means the
    worker also recovers anything left mid-flight by a crash) plus
    instances `waiting_external` whose retry-scheduled step is now due.

    Not using SELECT ... FOR UPDATE SKIP LOCKED here (see ADR-0002) —
    that's Phase 13 (Reliability) hardening for multi-replica safety; at
    one worker replica, a plain read is correct and simpler, and
    advance_workflow's own per-step commits are what make each step
    durable regardless.
    """
    running = db.scalars(
        select(WorkflowInstance).where(WorkflowInstance.status == InstanceStatus.RUNNING)
    ).all()

    due_external = db.scalars(
        select(WorkflowInstance)
        .join(
            WorkflowStepInstance,
            WorkflowStepInstance.workflow_instance_id == WorkflowInstance.id,
        )
        .where(
            WorkflowInstance.status == InstanceStatus.WAITING_EXTERNAL,
            WorkflowStepInstance.status == StepStatus.PENDING,
            WorkflowStepInstance.scheduled_at <= func.now(),
        )
        .distinct()
    ).all()

    by_id = {instance.id: instance for instance in (*running, *due_external)}
    return list(by_id.values())
