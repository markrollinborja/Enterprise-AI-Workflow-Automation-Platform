from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.workflow import WorkflowEvent, WorkflowInstance


def get_by_dedup_key(db: Session, dedup_key: str) -> WorkflowEvent | None:
    return db.scalar(select(WorkflowEvent).where(WorkflowEvent.dedup_key == dedup_key))


def create(db: Session, **fields: Any) -> WorkflowEvent:
    event = WorkflowEvent(**fields)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_for_timeline(
    db: Session, *, workflow_instance_id: UUID | None = None, limit: int = 100
) -> list[WorkflowEvent]:
    """Feeds services/dashboard/service.py's composed audit timeline the
    "workflow started" entry — see that module's docstring for why this
    isn't a dedicated AuditLog table. `workflow_instance_id=None` is the
    global Audit Log page's case: most-recent `limit` events, not a true
    global top-N across every audit source (see build_audit_timeline's own
    docstring on that tradeoff)."""
    query = select(WorkflowEvent).options(
        joinedload(WorkflowEvent.workflow_instance).joinedload(
            WorkflowInstance.workflow_definition
        ),
        joinedload(WorkflowEvent.workflow_instance).joinedload(WorkflowInstance.initiated_by),
    )
    if workflow_instance_id is not None:
        query = query.where(WorkflowEvent.workflow_instance_id == workflow_instance_id).order_by(
            WorkflowEvent.received_at
        )
    else:
        query = query.order_by(WorkflowEvent.received_at.desc()).limit(limit)
    return list(db.scalars(query))
