from typing import Any

from sqlalchemy.orm import Session

from app.models.mcp_tool_execution import MCPToolExecution


def create(db: Session, **fields: Any) -> MCPToolExecution:
    """No get/list helpers yet — same discipline as ai_execution_repo.py:
    nothing reads MCPToolExecution rows back in V1 (Phase 12's dashboard is
    the first planned consumer). Not adding unused query methods ahead of a
    real caller."""
    execution = MCPToolExecution(**fields)
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution
