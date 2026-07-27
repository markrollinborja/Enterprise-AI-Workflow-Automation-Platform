from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.approval import ApprovalDecisionCreate, ApprovalRequestResponse
from app.services.approvals import service as approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRequestResponse])
def list_my_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApprovalRequestResponse]:
    """Any authenticated user can call this — it always returns only what's
    actually relevant to them (assigned-to-them, their role's pool, or
    everything for Administrators). The filtering in
    approval_request_repo.list_pending_for_user IS the access control here;
    no route-level role gate is needed on top of it."""
    return approval_service.list_pending_for_user(db, current_user)


@router.post("/{approval_request_id}/decide", response_model=ApprovalRequestResponse)
def decide_approval(
    approval_request_id: UUID,
    payload: ApprovalDecisionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.MANAGER, UserRole.IT, UserRole.SECURITY, UserRole.ADMINISTRATOR)
    ),
) -> ApprovalRequestResponse:
    """Role-gated here at a coarse level (must be one of the roles that can
    ever approve something) — the fine-grained "is this specific approval
    actually yours" check happens in the service layer
    (`_authorize_decision`), since that depends on row data
    (`assigned_user_id`), not just which role the caller holds."""
    return approval_service.decide(
        db,
        approval_request_id,
        current_user,
        decision=payload.decision,
        notes=payload.notes,
    )
