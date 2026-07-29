"""Phase 6 adds list_ready_to_advance for the worker — everything else was
already enough for the engine (start_workflow/advance_workflow just need
get_by_id/create)."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.employee import Employee
from app.models.enums import InstanceStatus, StepStatus
from app.models.workflow import WorkflowInstance, WorkflowStepInstance


def get_by_id(db: Session, instance_id: UUID) -> WorkflowInstance | None:
    return db.get(WorkflowInstance, instance_id)


def get_by_id_with_relations(db: Session, instance_id: UUID) -> WorkflowInstance | None:
    """Same row as get_by_id, but with everything the Phase 12 workflow
    detail page needs eager-loaded in one query — steps, the definition
    name, employee, and who started it. Not used by the engine itself
    (which only ever needs the bare instance), so this stays a separate
    function rather than making every get_by_id caller pay for joins it
    doesn't need."""
    return db.scalar(
        select(WorkflowInstance)
        .where(WorkflowInstance.id == instance_id)
        .options(
            joinedload(WorkflowInstance.workflow_definition),
            joinedload(WorkflowInstance.employee).joinedload(Employee.department),
            joinedload(WorkflowInstance.initiated_by),
            selectinload(WorkflowInstance.step_instances),
        )
    )


def list_all(db: Session) -> list[WorkflowInstance]:
    """The Phase 12 dashboard's workflow-instance list — every instance,
    most-recently-active first. No pagination in V1: at this project's demo
    scale (a handful of seeded instances) a full table scan with eager
    loads is simpler and fast enough; a real paginated endpoint is what a
    production version would need once this table has thousands of rows,
    not sixteen. `employee.department` is eager-loaded too — the dashboard
    summary's "requests by department" aggregation reads it off this same
    result set rather than a second query."""
    return list(
        db.scalars(
            select(WorkflowInstance)
            .options(
                joinedload(WorkflowInstance.workflow_definition),
                joinedload(WorkflowInstance.employee).joinedload(Employee.department),
                joinedload(WorkflowInstance.initiated_by),
                selectinload(WorkflowInstance.step_instances),
            )
            .order_by(WorkflowInstance.updated_at.desc())
        )
    )


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
