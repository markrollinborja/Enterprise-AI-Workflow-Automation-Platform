"""Phase 12's read-only dashboard surface. Every route here is
Administrator-only — matches section 9 of the project spec ("Administrator:
View all workflows, View audit logs") rather than inventing a cross-
department visibility rule the spec doesn't actually ask for. Employee
Directory (Phase 4) and Pending Approvals (Phase 7) keep their existing,
broader access — this file doesn't touch either.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.enums import InstanceStatus, UserRole
from app.models.user import User
from app.schemas.dashboard import (
    AuditTimelineEntryResponse,
    DashboardSummaryResponse,
    WorkflowInstanceDetailResponse,
    WorkflowInstanceSummaryResponse,
)
from app.services.dashboard import service as dashboard_service

router = APIRouter(tags=["dashboard"])

_require_admin = require_role(UserRole.ADMINISTRATOR)


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    _current_user: User = Depends(_require_admin),
) -> DashboardSummaryResponse:
    return dashboard_service.get_summary(db)


@router.get("/workflow-instances", response_model=list[WorkflowInstanceSummaryResponse])
def list_workflow_instances(
    status: InstanceStatus | None = None,
    db: Session = Depends(get_db),
    _current_user: User = Depends(_require_admin),
) -> list[WorkflowInstanceSummaryResponse]:
    """`?status=failed` is also the Failed Workflows page's data source —
    see WorkflowInstanceSummaryResponse's docstring for why that's a query
    param on this endpoint rather than a second one."""
    return dashboard_service.list_workflow_instances(db, status=status)


@router.get("/workflow-instances/{instance_id}", response_model=WorkflowInstanceDetailResponse)
def get_workflow_instance(
    instance_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(_require_admin),
) -> WorkflowInstanceDetailResponse:
    return dashboard_service.get_workflow_instance_detail(db, instance_id)


@router.get("/audit-log", response_model=list[AuditTimelineEntryResponse])
def get_audit_log(
    db: Session = Depends(get_db),
    _current_user: User = Depends(_require_admin),
) -> list[AuditTimelineEntryResponse]:
    return dashboard_service.build_audit_timeline(db)
