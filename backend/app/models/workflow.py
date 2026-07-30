"""Workflow definition, instance, step-instance, and event models.

WorkflowDefinition is the versioned template (loaded from workflows/*.json
— see ADR-0003), WorkflowInstance is one running/completed process,
WorkflowStepInstance is one row per step per instance, WorkflowEvent is the
raw trigger record and idempotency boundary (Phase 6). No relational
step-definition table (ADR-0003), no separate IntegrationExecution/
IdempotencyKey tables (data-model.md's cuts still apply).
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
from app.models.enums import InstanceStatus, StepStatus, StepType, TriggerType, enum_values

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class WorkflowDefinition(Base):
    """The versioned template. `key` + `version` together identify a
    specific revision (e.g. `employee_onboarding` v1, v2, ...); `key` alone
    is NOT unique because a new version is a new row, not an in-place edit —
    that's what makes `WorkflowInstance.workflow_definition_id` point at an
    immutable snapshot instead of a template that could change out from
    under a running instance.

    Only one row per `key` should have `is_active=True` at a time. That's
    enforced by the loader (services/workflows/definition_loader.py), not a
    DB constraint — a partial unique index would be the "correct" enterprise
    answer, but with two workflows that only ever get reseeded (not
    versioned at runtime) in V1, application-level enforcement is enough;
    revisit if a real admin-facing "publish new version" flow gets built.
    """

    __tablename__ = "workflow_definitions"
    __table_args__ = ()

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    trigger_type: Mapped[TriggerType] = mapped_column(
        SAEnum(TriggerType, name="trigger_type", values_callable=enum_values),
        nullable=False,
    )
    trigger_event: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The full validated WorkflowDefinitionSchema, dumped to JSON — steps,
    # conditions, approval requirements, failure behavior. See
    # app/schemas/workflow_definition.py for the shape; that Pydantic model
    # is what actually gets validated, this column is just storage.
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkflowInstance(Base):
    """One running or completed process — one row per HR onboarding
    submission, one row per access request. `employee_id` is nullable
    because not every future workflow will necessarily concern a specific
    employee, though both V1 workflows do."""

    __tablename__ = "workflow_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_definitions.id"), nullable=False
    )
    status: Mapped[InstanceStatus] = mapped_column(
        SAEnum(InstanceStatus, name="instance_status", values_callable=enum_values),
        nullable=False,
        default=InstanceStatus.PENDING,
        index=True,
    )
    # The data the workflow was started with (e.g. {"employee_id": "..."}
    # for onboarding, {"employee_id": ..., "application_id": ..., "justification": ...}
    # for an access request) — validated against the definition's
    # input_schema by the (Phase 6) validation step, not at insert time here.
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    initiated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id"), nullable=True
    )
    current_step_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow_definition: Mapped["WorkflowDefinition"] = relationship()
    employee: Mapped["Employee | None"] = relationship()
    initiated_by: Mapped["User | None"] = relationship()
    step_instances: Mapped[list["WorkflowStepInstance"]] = relationship(
        back_populates="workflow_instance",
        order_by="WorkflowStepInstance.created_at",
        cascade="all, delete-orphan",
    )


class WorkflowStepInstance(Base):
    """One row per step per instance, in execution order (see
    `created_at` ordering on the parent's `step_instances` relationship —
    the JSON definition's step order is the authoritative order; `created_at`
    just needs to agree with it, which the Phase 6 engine guarantees by
    creating rows in definition order).

    A retried step does NOT get a new row — `attempt_count` increments and
    the same row re-enters `pending`. That's what lets the audit trail show
    "both attempts" for the integration-failure-and-retry demo scenario from
    a single row's history instead of reconstructing it across rows.
    """

    __tablename__ = "workflow_step_instances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    step_type: Mapped[StepType] = mapped_column(
        SAEnum(StepType, name="step_type", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[StepStatus] = mapped_column(
        SAEnum(StepStatus, name="step_status", values_callable=enum_values),
        nullable=False,
        default=StepStatus.PENDING,
    )
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # The Jira issue key (e.g. "ONB-1234") once this step's create_jira_task
    # call succeeds, for steps that await fulfillment confirmation (ADR-0010,
    # Phase 10 checkpoint 3) — what /webhooks/jira looks a step up by. Not
    # unique: mock mode's fake issue keys aren't guaranteed globally unique
    # (see mcp_server/app/tools/jira.py), only real Jira Cloud keys are.
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 13b: set only by services/workflows/service.py::retry_failed_step,
    # never by the normal engine loop — distinct from attempt_count (which
    # also increments on automatic backoff retries) so the audit trail can
    # tell "the engine retried this itself" from "an admin intervened."
    retried_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    retried_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_instance: Mapped["WorkflowInstance"] = relationship(back_populates="step_instances")
    retried_by: Mapped["User | None"] = relationship()


class WorkflowEvent(Base):
    """The raw external trigger record — and the idempotency boundary.

    `dedup_key` (e.g. `employee_onboarding:{employee_id}`) has a unique DB
    constraint. If the same trigger arrives twice (a duplicate webhook
    retry, a double form submission), the second `start_workflow` call
    finds this row by `dedup_key` and returns the already-running instance
    instead of creating a second one. This is what data-model.md's cut of a
    separate IdempotencyKey table refers to — the event that starts a
    workflow *is* the idempotency check, not a second table for the same
    concept. See docs/architecture/workflow-state-model.md.
    """

    __tablename__ = "workflow_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=True
    )

    workflow_instance: Mapped["WorkflowInstance | None"] = relationship()
