"""Owns the human-facing side of approvals: what's in my inbox, and
recording + acting on a decision.

Does NOT create ApprovalRequest rows — that happens directly in
`services/workflows/service.py` when a step pauses (see that module's
`_create_approval_request`). This module depends on
`services/workflows/service.py` (to call `resume_workflow_step` once a
decision is made); the dependency only ever points one way, which is what
avoids a circular import between the two service modules. See
docs/architecture/service-boundaries.md for the full reasoning.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalRequestStatus, UserRole
from app.models.user import User
from app.repositories import approval_decision_repo, approval_request_repo, notification_repo
from app.schemas.approval import ApprovalRequestResponse
from app.services.workflows.service import resume_workflow_step


def _to_response(approval_request: ApprovalRequest) -> ApprovalRequestResponse:
    instance = approval_request.workflow_instance
    definition = instance.workflow_definition
    step_key = approval_request.step_instance.step_key

    step_defs_by_key = {s["key"]: s for s in definition.definition_json["steps"]}
    step_name = step_defs_by_key.get(step_key, {}).get("name", step_key)

    employee = instance.employee
    employee_name = f"{employee.first_name} {employee.last_name}" if employee else None

    return ApprovalRequestResponse(
        id=approval_request.id,
        workflow_instance_id=instance.id,
        workflow_name=definition.name,
        step_key=step_key,
        step_name=step_name,
        employee_name=employee_name,
        approver_role=approval_request.approver_role.value,
        sequence_order=approval_request.sequence_order,
        status=approval_request.status.value,
        assigned_user_id=approval_request.assigned_user_id,
        requested_at=approval_request.created_at,
        due_at=approval_request.due_at,
    )


def list_pending_for_user(db: Session, user: User) -> list[ApprovalRequestResponse]:
    return [_to_response(a) for a in approval_request_repo.list_pending_for_user(db, user)]


def _authorize_decision(approval_request: ApprovalRequest, current_user: User) -> None:
    """Administrator can act on anything (oversight). A specifically
    assigned approval (currently: manager_approval, resolved to the
    employee's actual manager) can only be decided by that exact user —
    even another manager isn't allowed to pick it up. A role-pool approval
    (IT, Security) can be decided by anyone holding that role."""
    if current_user.role == UserRole.ADMINISTRATOR:
        return
    if approval_request.assigned_user_id is not None:
        if approval_request.assigned_user_id != current_user.id:
            raise PermissionDeniedError("This approval is assigned to a different user.")
        return
    if approval_request.approver_role != current_user.role:
        raise PermissionDeniedError(
            f"This approval requires the '{approval_request.approver_role.value}' role."
        )


def decide(
    db: Session,
    approval_request_id: UUID,
    current_user: User,
    *,
    decision: Literal["approved", "rejected"],
    notes: str | None = None,
) -> ApprovalRequestResponse:
    approval_request = approval_request_repo.get_by_id(db, approval_request_id)
    if approval_request is None:
        raise NotFoundError("Approval request not found.")
    # ApprovalRequest.status doesn't need state_machine.py-style enforcement
    # the way WorkflowInstance/WorkflowStepInstance do — it has exactly one
    # transition point (this function) and exactly one guard (this check),
    # versus the engine's status fields being written from many places
    # across service.py, which is what actually makes a shared transition
    # table worth having.
    if approval_request.status != ApprovalRequestStatus.PENDING:
        raise ConflictError("This approval has already been decided.")

    _authorize_decision(approval_request, current_user)

    decision_status = (
        ApprovalRequestStatus.APPROVED if decision == "approved" else ApprovalRequestStatus.REJECTED
    )
    approval_decision_repo.create(
        db,
        approval_request_id=approval_request.id,
        decided_by_user_id=current_user.id,
        decision=decision_status,
        notes=notes,
    )
    approval_request.status = decision_status
    db.add(approval_request)
    db.commit()

    # Clears the "Approval needed" in-app notification that put this in the
    # deciding user's queue — without this, acting on the approval here
    # left that notification unread forever unless separately dismissed
    # from the Notifications panel (a confusing double action for the same
    # thing). See notification_repo.mark_approval_requested_read's
    # docstring for why user_id + workflow_instance_id is precise enough
    # without a dedicated step_instance_id link.
    notification_repo.mark_approval_requested_read(
        db,
        user_id=current_user.id,
        workflow_instance_id=approval_request.workflow_instance_id,
    )

    # Advances (or terminates) the underlying workflow instance — the real
    # counterpart to what Phase 6's tests simulated by calling this
    # directly.
    resume_workflow_step(
        db,
        approval_request.workflow_instance,
        approval_request.step_instance,
        decision=decision,
        notes=notes,
    )

    db.refresh(approval_request)
    return _to_response(approval_request)
