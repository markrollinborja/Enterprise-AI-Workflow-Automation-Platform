from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.ai_execution import AIExecution
from app.models.workflow import WorkflowInstance


def create(db: Session, **fields: Any) -> AIExecution:
    execution = AIExecution(**fields)
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def list_for_timeline(
    db: Session, *, workflow_instance_id: UUID | None = None, limit: int = 100
) -> list[AIExecution]:
    """Phase 12's dashboard is the first real reader of AIExecution rows —
    both the workflow detail page's "AI output" section and the composed
    audit timeline's "AI called" entries. See
    services/dashboard/service.py."""
    query = select(AIExecution).options(
        joinedload(AIExecution.step_instance),
        joinedload(AIExecution.workflow_instance).joinedload(WorkflowInstance.workflow_definition),
    )
    if workflow_instance_id is not None:
        query = query.where(AIExecution.workflow_instance_id == workflow_instance_id).order_by(
            AIExecution.created_at
        )
    else:
        query = query.order_by(AIExecution.created_at.desc()).limit(limit)
    return list(db.scalars(query))
