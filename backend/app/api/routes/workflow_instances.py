"""Phase 13b: admin-only write actions against a workflow instance.

Deliberately its own file, not folded into dashboard.py — that file's own
docstring documents it as "Phase 12's read-only dashboard surface," and
nothing in it writes anything today. Manual retry is the first write
action against a workflow instance that isn't shaped like an approval
decision (approvals.py) or an external webhook (webhooks.py), so it gets
a home that doesn't quietly break dashboard.py's documented invariant.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import workflow_instance_repo, workflow_step_repo
from app.schemas.dashboard import WorkflowInstanceDetailResponse
from app.services.dashboard import service as dashboard_service
from app.services.workflows.service import retry_failed_step

router = APIRouter(tags=["workflow-instances"])

_require_admin = require_role(UserRole.ADMINISTRATOR)


@router.post(
    "/workflow-instances/{instance_id}/steps/{step_key}/retry",
    response_model=WorkflowInstanceDetailResponse,
)
def retry_step(
    instance_id: UUID,
    step_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin),
) -> WorkflowInstanceDetailResponse:
    """Resets a FAILED step to PENDING (scheduled_at = now) and un-terminals
    its instance if the failure had taken that down too, then re-runs the
    engine's normal advance logic inline — see
    services/workflows/service.py::retry_failed_step for the state-machine
    and audit-trail reasoning. Raises 404 if the instance or step doesn't
    exist, 409 (via ConflictError) if the step isn't currently FAILED.
    """
    instance = workflow_instance_repo.get_by_id(db, instance_id)
    if instance is None:
        raise NotFoundError("Workflow instance not found")

    step_row = workflow_step_repo.get_by_instance_and_key(db, instance_id, step_key)
    if step_row is None:
        raise NotFoundError(f"No step '{step_key}' on this workflow instance")

    retry_failed_step(db, instance, step_row, retried_by_user_id=current_user.id)
    return dashboard_service.get_workflow_instance_detail(db, instance_id)
