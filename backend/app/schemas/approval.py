from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ApprovalRequestResponse(BaseModel):
    """Not a from_attributes pass-through — workflow_name, step_name, and
    employee_name are derived by the service layer from joined relationships
    (see services/approvals/service.py::_to_response), same pattern as
    EmployeeResponse's department_name/manager_name."""

    id: UUID
    workflow_instance_id: UUID
    workflow_name: str
    step_key: str
    step_name: str
    employee_name: str | None
    approver_role: str
    sequence_order: int
    status: str
    assigned_user_id: UUID | None
    requested_at: datetime
    due_at: datetime | None


class ApprovalDecisionCreate(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str | None = None
