from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.approval import ApprovalDecision, ApprovalRequest
from app.models.enums import ApprovalRequestStatus, UserRole
from app.models.user import User
from app.models.workflow import WorkflowInstance


def get_by_id(db: Session, approval_request_id: UUID) -> ApprovalRequest | None:
    return db.get(ApprovalRequest, approval_request_id)


def get_by_step_instance_id(db: Session, step_instance_id: UUID) -> ApprovalRequest | None:
    return db.scalar(
        select(ApprovalRequest).where(ApprovalRequest.step_instance_id == step_instance_id)
    )


def create(db: Session, **fields: Any) -> ApprovalRequest:
    approval_request = ApprovalRequest(**fields)
    db.add(approval_request)
    db.commit()
    db.refresh(approval_request)
    return approval_request


def list_pending_for_user(db: Session, user: User) -> list[ApprovalRequest]:
    """Administrator sees every pending approval (oversight, matches the
    role's "view all workflows" scope). Everyone else sees what's assigned
    to them by name, plus anything unassigned in their role's pool (IT,
    Security) — see ApprovalRequest's docstring for the assignment rule."""
    query = select(ApprovalRequest).where(ApprovalRequest.status == ApprovalRequestStatus.PENDING)
    if user.role != UserRole.ADMINISTRATOR:
        query = query.where(
            or_(
                ApprovalRequest.assigned_user_id == user.id,
                (ApprovalRequest.assigned_user_id.is_(None))
                & (ApprovalRequest.approver_role == user.role),
            )
        )
    query = query.order_by(ApprovalRequest.created_at)
    return list(db.scalars(query))


def count_pending(db: Session) -> int:
    """The dashboard summary's "pending approvals" count — every pending
    request org-wide (an Administrator's-eye view), not filtered to one
    user like list_pending_for_user."""
    return (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalRequestStatus.PENDING)
        )
        or 0
    )


def list_for_timeline(
    db: Session, *, workflow_instance_id: UUID | None = None, limit: int = 100
) -> list[ApprovalRequest]:
    """Feeds the Phase 12 composed audit timeline two entry types per row:
    "approval requested" (this row itself) and "approval decided" (each of
    its `decisions`, usually zero or one). See
    services/dashboard/service.py::build_audit_timeline."""
    query = select(ApprovalRequest).options(
        joinedload(ApprovalRequest.step_instance),
        joinedload(ApprovalRequest.assigned_user),
        joinedload(ApprovalRequest.workflow_instance).joinedload(
            WorkflowInstance.workflow_definition
        ),
        selectinload(ApprovalRequest.decisions).joinedload(ApprovalDecision.decided_by),
    )
    if workflow_instance_id is not None:
        query = query.where(ApprovalRequest.workflow_instance_id == workflow_instance_id).order_by(
            ApprovalRequest.created_at
        )
    else:
        query = query.order_by(ApprovalRequest.created_at.desc()).limit(limit)
    return list(db.scalars(query))
