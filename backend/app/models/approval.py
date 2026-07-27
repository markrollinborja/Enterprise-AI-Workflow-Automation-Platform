"""ApprovalRequest is the human-facing record ("something is waiting on
me"); ApprovalDecision is the record of what was actually decided. Kept
separate from WorkflowStepInstance (which already tracks WAITING_APPROVAL/
COMPLETED/REJECTED for the engine) because the engine's step state and a
human-readable approval inbox are different concerns — see
docs/architecture/service-boundaries.md's "approvals" section for the full
reasoning, including why creation happens in the workflow engine directly
rather than through the approvals service (avoids a circular dependency
between services/workflows and services/approvals).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import ApprovalRequestStatus, UserRole, enum_values

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workflow import WorkflowInstance, WorkflowStepInstance


class ApprovalRequest(Base):
    """One row per approval step that has actually paused waiting for a
    human — created the moment `advance_workflow` transitions a step to
    `waiting_approval`, not upfront when the instance starts (an approval
    that never gets reached, e.g. `it_review_access` when the AI didn't
    flag review, should never appear in anyone's inbox).

    `assigned_user_id` is set when there's a specific person (currently:
    the employee's actual manager, resolved from `Employee.manager_id`) and
    left null for role-based pool approvals (IT, Security) — see
    services/workflows/service.py's `_resolve_approver` for the resolution
    rule.
    """

    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=False, index=True
    )
    step_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_step_instances.id"), nullable=False, index=True
    )
    approver_role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=enum_values),
        nullable=False,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    status: Mapped[ApprovalRequestStatus] = mapped_column(
        SAEnum(ApprovalRequestStatus, name="approval_request_status", values_callable=enum_values),
        nullable=False,
        default=ApprovalRequestStatus.PENDING,
        index=True,
    )
    # Mirrors the step's ApprovalStepConfig.sequence_order — display-only in
    # V1 (e.g. "step 2 of 3"), not enforced here; sequencing is already
    # enforced by the engine only pausing on one approval step at a time.
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_instance: Mapped["WorkflowInstance"] = relationship()
    step_instance: Mapped["WorkflowStepInstance"] = relationship()
    assigned_user: Mapped["User | None"] = relationship()
    decisions: Mapped[list["ApprovalDecision"]] = relationship(back_populates="approval_request")


class ApprovalDecision(Base):
    """The actual decision — kept as its own row (not just a status flip on
    ApprovalRequest) so there's a durable, queryable audit record of who
    decided what and when, independent of anything the workflow engine
    later does with that decision."""

    __tablename__ = "approval_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("approval_requests.id"), nullable=False, index=True
    )
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    # Reuses the same Postgres enum type as ApprovalRequest.status (see
    # migration 0006 — the type is created once and referenced with
    # create_type=False the second time, not recreated).
    decision: Mapped[ApprovalRequestStatus] = mapped_column(
        SAEnum(ApprovalRequestStatus, name="approval_request_status", values_callable=enum_values),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    approval_request: Mapped["ApprovalRequest"] = relationship(back_populates="decisions")
    decided_by: Mapped["User"] = relationship()
