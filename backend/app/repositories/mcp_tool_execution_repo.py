from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.mcp_tool_execution import MCPToolExecution
from app.models.workflow import WorkflowInstance


def create(db: Session, **fields: Any) -> MCPToolExecution:
    execution = MCPToolExecution(**fields)
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


def list_for_timeline(
    db: Session, *, workflow_instance_id: UUID | None = None, limit: int = 100
) -> list[MCPToolExecution]:
    """Phase 12's dashboard is the first real reader — the workflow detail
    page's "MCP tool executions" section and the composed audit timeline's
    "integration called" entries. See services/dashboard/service.py."""
    query = select(MCPToolExecution).options(
        joinedload(MCPToolExecution.step_instance),
        joinedload(MCPToolExecution.workflow_instance).joinedload(
            WorkflowInstance.workflow_definition
        ),
    )
    if workflow_instance_id is not None:
        query = query.where(
            MCPToolExecution.workflow_instance_id == workflow_instance_id
        ).order_by(MCPToolExecution.created_at)
    else:
        query = query.order_by(MCPToolExecution.created_at.desc()).limit(limit)
    return list(db.scalars(query))
