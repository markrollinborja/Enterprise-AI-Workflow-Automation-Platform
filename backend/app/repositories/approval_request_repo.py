from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalRequestStatus, UserRole
from app.models.user import User


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
