"""One row per AI call attempt — success or failure — from either an
ai_action workflow step (the only caller in V1; AI-as-agent calling MCP
tools is a Phase 10+ extension, see ADR discussion in
docs/architecture/service-boundaries.md's "ai" section). This is the audit
trail Principle 4 asks for: "AI called" / "AI result returned" as their own
inspectable rows, not just a side effect buried in a step's output_data.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import AIExecutionStatus, AITaskType, enum_values

if TYPE_CHECKING:
    from app.models.workflow import WorkflowInstance, WorkflowStepInstance


class AIExecution(Base):
    __tablename__ = "ai_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=False, index=True
    )
    step_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_step_instances.id"), nullable=False, index=True
    )
    task_type: Mapped[AITaskType] = mapped_column(
        SAEnum(AITaskType, name="ai_task_type", values_callable=enum_values),
        nullable=False,
    )
    # A short, human-readable description of what was sent to the model
    # (e.g. "job_title=Software Engineer, department=Engineering") — not
    # the full prompt. Full prompts/responses aren't persisted: they're not
    # needed for the audit story this table exists to tell, and it keeps
    # this table from becoming a place sensitive free-text (a justification,
    # a job description) accumulates by accident.
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # The full structured (validated) output on success; null on failure.
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_human_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[AIExecutionStatus] = mapped_column(
        SAEnum(AIExecutionStatus, name="ai_execution_status", values_callable=enum_values),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_instance: Mapped["WorkflowInstance"] = relationship()
    step_instance: Mapped["WorkflowStepInstance"] = relationship()
