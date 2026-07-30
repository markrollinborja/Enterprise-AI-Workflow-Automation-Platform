"""Response shapes for Phase 12's read-only dashboard surface —
GET /dashboard/summary, GET /workflow-instances (+ /{id}), GET /audit-log.
Every field here is derived from data services/workflows/service.py,
services/approvals/service.py, services/ai/service.py,
services/integrations/mcp_client.py, and services/notifications/service.py
already write for their own reasons; nothing in this file introduces a new
write path (see services/dashboard/service.py's module docstring for why
there's no dedicated AuditLog table backing AuditTimelineEntryResponse).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    active_workflows: int
    pending_approvals: int
    failed_workflows: int
    completed_workflows: int
    # None when there are zero completed instances yet — avoid a bogus 0.0
    # that would read as "completes instantly."
    avg_completion_seconds: float | None
    requests_by_type: dict[str, int]
    requests_by_department: dict[str, int]


class WorkflowInstanceSummaryResponse(BaseModel):
    """One row in the Workflow Instances list. The three `failed_*` fields
    are only populated when `status == "failed"` — same response shape
    doubles as the Failed Workflows view via `GET /workflow-instances?status=failed`
    rather than a second endpoint/schema for what's otherwise an identical
    row."""

    id: UUID
    workflow_key: str
    workflow_name: str
    employee_name: str | None
    initiated_by_name: str | None
    status: str
    current_step_key: str | None
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    failed_step_key: str | None
    failure_reason: str | None
    failed_attempt_count: int | None


class WorkflowStepDetailResponse(BaseModel):
    id: UUID
    step_key: str
    step_type: str
    status: str
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    attempt_count: int
    scheduled_at: datetime | None
    external_ref: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    # Phase 13b: set only when an admin manually retried this step — None
    # for a step that's never failed, or was only ever retried
    # automatically (see attempt_count for that count).
    retried_by_name: str | None
    retried_at: datetime | None


class ApprovalDecisionDetailResponse(BaseModel):
    id: UUID
    decided_by_name: str
    decision: str
    notes: str | None
    decided_at: datetime


class ApprovalDetailResponse(BaseModel):
    id: UUID
    step_key: str
    approver_role: str
    assigned_user_name: str | None
    status: str
    sequence_order: int
    due_at: datetime | None
    created_at: datetime
    decisions: list[ApprovalDecisionDetailResponse]


class AIExecutionDetailResponse(BaseModel):
    id: UUID
    step_key: str
    task_type: str
    input_summary: str
    output_json: dict[str, Any] | None
    confidence_score: float | None
    requires_human_review: bool | None
    model_used: str
    tokens_used: int | None
    status: str
    error_message: str | None
    created_at: datetime


class MCPToolExecutionDetailResponse(BaseModel):
    id: UUID
    step_key: str | None
    tool_name: str
    caller: str
    input_params: dict[str, Any]
    output_result: dict[str, Any] | None
    status: str
    mock_mode: bool
    duration_ms: int | None
    error_message: str | None
    created_at: datetime


class NotificationDetailResponse(BaseModel):
    id: UUID
    recipient_name: str
    type: str
    channel: str
    status: str
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class AuditTimelineEntryResponse(BaseModel):
    """One normalized row from the composed audit timeline — see
    services/dashboard/service.py::build_audit_timeline. Deliberately
    mirrors the original Phase 1 AuditLog column sketch (timestamp, actor,
    actor_type, action, resource_type, resource_id, outcome, metadata) even
    though there's no AuditLog table behind it; that's what makes this
    response shape a drop-in replacement if a real write-side AuditLog
    table is ever actually justified later."""

    timestamp: datetime
    actor: str
    actor_type: str
    action: str
    resource_type: str
    resource_id: UUID | None
    workflow_instance_id: UUID | None
    workflow_name: str | None
    outcome: str
    metadata: dict[str, Any]


class WorkflowInstanceDetailResponse(BaseModel):
    id: UUID
    workflow_key: str
    workflow_name: str
    status: str
    input_data: dict[str, Any]
    employee_name: str | None
    initiated_by_name: str | None
    current_step_key: str | None
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    steps: list[WorkflowStepDetailResponse]
    approvals: list[ApprovalDetailResponse]
    ai_executions: list[AIExecutionDetailResponse]
    mcp_tool_executions: list[MCPToolExecutionDetailResponse]
    notifications: list[NotificationDetailResponse]
    audit_timeline: list[AuditTimelineEntryResponse]
