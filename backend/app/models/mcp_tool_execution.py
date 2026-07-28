"""The single audit table for every Jira/Slack/Calendar/employee-lookup
call, from either caller (workflow engine or the AI agent's tool-calling
loop) — see data-model.md's cut of a separate IntegrationExecution table
("every external integration in this project is invoked through MCP, so a
separate generic audit table would just duplicate this one row-for-row").

Both `workflow_instance_id` and `step_instance_id` are nullable: an
AI-agent-initiated `lookup_employee` call happens *during* a
recommend_access step's execution, so it's still tied to a step, but a
future tool call made outside any workflow context (none exist in V1)
would have nowhere else to attach.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import MCPExecutionStatus, MCPToolCaller, enum_values

if TYPE_CHECKING:
    from app.models.workflow import WorkflowInstance, WorkflowStepInstance


class MCPToolExecution(Base):
    __tablename__ = "mcp_tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    caller: Mapped[MCPToolCaller] = mapped_column(
        SAEnum(MCPToolCaller, name="mcp_tool_caller", values_callable=enum_values),
        nullable=False,
    )
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=True, index=True
    )
    step_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_step_instances.id"), nullable=True, index=True
    )
    # Redacted before persisting — see docs/architecture/data-model.md's
    # redaction note. No raw secrets (Jira/Slack/Google tokens) ever land
    # here; input_params/output_result are the tool's own typed
    # input/output schemas, which don't carry credentials as fields.
    input_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[MCPExecutionStatus] = mapped_column(
        SAEnum(MCPExecutionStatus, name="mcp_execution_status", values_callable=enum_values),
        nullable=False,
    )
    # Whether mcp_server actually called Jira/Slack/Calendar for real, or
    # returned a canned mock response (MCP_MOCK_MODE) — kept here, not just
    # inferred from settings at read time, because mock/real can change
    # between when a row was written and when someone reads it back.
    mock_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Always 1 today — services/integrations/mcp_client.py does not retry
    # internally (see ADR-0012); the workflow engine's own step-level retry
    # is what re-invokes execute_mcp_tool, which writes a fresh row per
    # attempt. This column exists so a future caller could distinguish
    # "attempt 2 of this step" without joining back through
    # WorkflowStepInstance.attempt_count.
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_instance: Mapped["WorkflowInstance | None"] = relationship()
    step_instance: Mapped["WorkflowStepInstance | None"] = relationship()
