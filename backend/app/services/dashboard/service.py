"""Dashboard read-model for Phase 12 — backs GET /dashboard/summary,
GET /workflow-instances (+ /{id}), and GET /audit-log. Purely a read layer:
nothing here writes anything, and api/routes/dashboard.py is its only
caller.

No dedicated AuditLog table backs build_audit_timeline(). Every event
Principle 4 asks to be auditable is already a real row somewhere:
WorkflowEvent (workflow started), ApprovalRequest/ApprovalDecision
(approval requested/decided), AIExecution (AI called), MCPToolExecution
(integration called), Notification (notification sent), and
WorkflowInstance's own terminal status (workflow completed/failed/
rejected/cancelled — synthesized here from status + completed_at, not a
seventh source table). Standing up a write-side AuditLog table would mean
writing every one of those events a second time, for a screen that only
ever reads them back in chronological order — the same reasoning behind
data-model.md's existing IntegrationExecution/IdempotencyKey cuts, applied
one level up.

Known V1 scale limit: the global (workflow_instance_id=None) timeline pulls
each source's most recent `limit` rows independently, then merges and
re-sorts — not a true global top-N across all sources, which would need a
real UNION query. Not worth building at this project's demo scale
(Principle 1: realism, not enterprise scale); revisit if this table ever
holds more than a few hundred rows per source.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.ai_execution import AIExecution
from app.models.approval import ApprovalDecision, ApprovalRequest
from app.models.employee import Employee
from app.models.enums import InstanceStatus, MCPToolCaller, StepStatus
from app.models.mcp_tool_execution import MCPToolExecution
from app.models.notification import Notification
from app.models.user import User
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.repositories import (
    ai_execution_repo,
    approval_request_repo,
    mcp_tool_execution_repo,
    notification_repo,
    workflow_event_repo,
    workflow_instance_repo,
)
from app.schemas.dashboard import (
    AIExecutionDetailResponse,
    ApprovalDecisionDetailResponse,
    ApprovalDetailResponse,
    AuditTimelineEntryResponse,
    DashboardSummaryResponse,
    MCPToolExecutionDetailResponse,
    NotificationDetailResponse,
    WorkflowInstanceDetailResponse,
    WorkflowInstanceSummaryResponse,
    WorkflowStepDetailResponse,
)

_ACTIVE_STATUSES = (
    InstanceStatus.PENDING,
    InstanceStatus.RUNNING,
    InstanceStatus.WAITING_APPROVAL,
    InstanceStatus.WAITING_EXTERNAL,
)

# Maps a terminal InstanceStatus to the timeline entry's outcome string.
_TERMINAL_OUTCOMES = {
    InstanceStatus.COMPLETED: "success",
    InstanceStatus.FAILED: "failure",
    InstanceStatus.REJECTED: "rejected",
    InstanceStatus.CANCELLED: "cancelled",
}


def _employee_name(employee: Employee | None) -> str | None:
    return f"{employee.first_name} {employee.last_name}" if employee else None


def _user_name(user: User | None) -> str | None:
    return user.full_name if user else None


def _actor(user: User | None) -> tuple[str, str]:
    """(actor name, actor_type) for a timeline entry — "system" when
    there's no linked user, e.g. a seed-created instance with no
    initiated_by."""
    if user is None:
        return "System", "system"
    return user.full_name, "user"


def _last_failed_step(instance: WorkflowInstance) -> WorkflowStepInstance | None:
    failed = [s for s in instance.step_instances if s.status == StepStatus.FAILED]
    return max(failed, key=lambda s: s.created_at) if failed else None


def _completed_at_key(instance: WorkflowInstance) -> datetime:
    """Sort key for terminal instances in the global audit timeline —
    a plain `lambda i: i.completed_at` can't be typed as returning a bare
    `datetime` (the column is `datetime | None`), even though every caller
    here has already filtered out the None case. The assert lets mypy
    narrow the type instead of silencing it with an ignore comment."""
    assert instance.completed_at is not None
    return instance.completed_at


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def get_summary(db: Session) -> DashboardSummaryResponse:
    instances = workflow_instance_repo.list_all(db)

    completed = [i for i in instances if i.status == InstanceStatus.COMPLETED]
    durations = [
        (i.completed_at - i.started_at).total_seconds()
        for i in completed
        if i.started_at is not None and i.completed_at is not None
    ]

    requests_by_type: dict[str, int] = {}
    requests_by_department: dict[str, int] = {}
    for instance in instances:
        type_key = instance.workflow_definition.name
        requests_by_type[type_key] = requests_by_type.get(type_key, 0) + 1
        if instance.employee is not None:
            dept_key = instance.employee.department.name
            requests_by_department[dept_key] = requests_by_department.get(dept_key, 0) + 1

    return DashboardSummaryResponse(
        active_workflows=sum(1 for i in instances if i.status in _ACTIVE_STATUSES),
        pending_approvals=approval_request_repo.count_pending(db),
        failed_workflows=sum(1 for i in instances if i.status == InstanceStatus.FAILED),
        completed_workflows=len(completed),
        avg_completion_seconds=(sum(durations) / len(durations)) if durations else None,
        requests_by_type=requests_by_type,
        requests_by_department=requests_by_department,
    )


# ---------------------------------------------------------------------------
# Workflow instance list + detail
# ---------------------------------------------------------------------------


def list_workflow_instances(
    db: Session, *, status: InstanceStatus | None = None
) -> list[WorkflowInstanceSummaryResponse]:
    """`status=failed` is how the Failed Workflows page reuses this same
    endpoint/response shape instead of a second one — see
    WorkflowInstanceSummaryResponse's docstring."""
    instances = workflow_instance_repo.list_all(db)
    if status is not None:
        instances = [i for i in instances if i.status == status]
    return [_to_summary(i) for i in instances]


def _to_summary(instance: WorkflowInstance) -> WorkflowInstanceSummaryResponse:
    failed_step_key = failure_reason = None
    failed_attempt_count = None
    if instance.status == InstanceStatus.FAILED:
        failed_step = _last_failed_step(instance)
        if failed_step is not None:
            failed_step_key = failed_step.step_key
            failure_reason = failed_step.error_message
            failed_attempt_count = failed_step.attempt_count

    return WorkflowInstanceSummaryResponse(
        id=instance.id,
        workflow_key=instance.workflow_definition.key,
        workflow_name=instance.workflow_definition.name,
        employee_name=_employee_name(instance.employee),
        initiated_by_name=_user_name(instance.initiated_by),
        status=instance.status.value,
        current_step_key=instance.current_step_key,
        started_at=instance.started_at,
        updated_at=instance.updated_at,
        completed_at=instance.completed_at,
        failed_step_key=failed_step_key,
        failure_reason=failure_reason,
        failed_attempt_count=failed_attempt_count,
    )


def get_workflow_instance_detail(
    db: Session, instance_id: UUID
) -> WorkflowInstanceDetailResponse:
    instance = workflow_instance_repo.get_by_id_with_relations(db, instance_id)
    if instance is None:
        raise NotFoundError("Workflow instance not found")

    approvals = approval_request_repo.list_for_timeline(db, workflow_instance_id=instance_id)
    ai_executions = ai_execution_repo.list_for_timeline(db, workflow_instance_id=instance_id)
    mcp_executions = mcp_tool_execution_repo.list_for_timeline(
        db, workflow_instance_id=instance_id
    )
    notifications = notification_repo.list_for_timeline(db, workflow_instance_id=instance_id)

    return WorkflowInstanceDetailResponse(
        id=instance.id,
        workflow_key=instance.workflow_definition.key,
        workflow_name=instance.workflow_definition.name,
        status=instance.status.value,
        input_data=instance.input_data,
        employee_name=_employee_name(instance.employee),
        initiated_by_name=_user_name(instance.initiated_by),
        current_step_key=instance.current_step_key,
        started_at=instance.started_at,
        updated_at=instance.updated_at,
        completed_at=instance.completed_at,
        steps=[_step_response(s) for s in instance.step_instances],
        approvals=[_approval_response(a) for a in approvals],
        ai_executions=[_ai_response(e) for e in ai_executions],
        mcp_tool_executions=[_mcp_response(e) for e in mcp_executions],
        notifications=[_notification_response(n) for n in notifications],
        audit_timeline=build_audit_timeline(db, workflow_instance_id=instance_id),
    )


def _step_response(step: WorkflowStepInstance) -> WorkflowStepDetailResponse:
    return WorkflowStepDetailResponse(
        id=step.id,
        step_key=step.step_key,
        step_type=step.step_type.value,
        status=step.status.value,
        input_data=step.input_data,
        output_data=step.output_data,
        attempt_count=step.attempt_count,
        scheduled_at=step.scheduled_at,
        external_ref=step.external_ref,
        started_at=step.started_at,
        completed_at=step.completed_at,
        error_message=step.error_message,
        created_at=step.created_at,
        retried_by_name=_user_name(step.retried_by),
        retried_at=step.retried_at,
    )


def _approval_response(approval: ApprovalRequest) -> ApprovalDetailResponse:
    return ApprovalDetailResponse(
        id=approval.id,
        step_key=approval.step_instance.step_key,
        approver_role=approval.approver_role.value,
        assigned_user_name=_user_name(approval.assigned_user),
        status=approval.status.value,
        sequence_order=approval.sequence_order,
        due_at=approval.due_at,
        created_at=approval.created_at,
        decisions=[
            ApprovalDecisionDetailResponse(
                id=d.id,
                decided_by_name=_user_name(d.decided_by) or "Unknown",
                decision=d.decision.value,
                notes=d.notes,
                decided_at=d.decided_at,
            )
            for d in approval.decisions
        ],
    )


def _ai_response(execution: AIExecution) -> AIExecutionDetailResponse:
    return AIExecutionDetailResponse(
        id=execution.id,
        step_key=execution.step_instance.step_key,
        task_type=execution.task_type.value,
        input_summary=execution.input_summary,
        output_json=execution.output_json,
        confidence_score=execution.confidence_score,
        requires_human_review=execution.requires_human_review,
        model_used=execution.model_used,
        tokens_used=execution.tokens_used,
        status=execution.status.value,
        error_message=execution.error_message,
        created_at=execution.created_at,
    )


def _mcp_response(execution: MCPToolExecution) -> MCPToolExecutionDetailResponse:
    return MCPToolExecutionDetailResponse(
        id=execution.id,
        step_key=execution.step_instance.step_key if execution.step_instance else None,
        tool_name=execution.tool_name,
        caller=execution.caller.value,
        input_params=execution.input_params,
        output_result=execution.output_result,
        status=execution.status.value,
        mock_mode=execution.mock_mode,
        duration_ms=execution.duration_ms,
        error_message=execution.error_message,
        created_at=execution.created_at,
    )


def _notification_response(notification: Notification) -> NotificationDetailResponse:
    return NotificationDetailResponse(
        id=notification.id,
        recipient_name=_user_name(notification.user) or "Unknown",
        type=notification.type.value,
        channel=notification.channel.value,
        status=notification.status.value,
        title=notification.title,
        body=notification.body,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


# ---------------------------------------------------------------------------
# Composed audit timeline
# ---------------------------------------------------------------------------


def _terminal_entry(instance: WorkflowInstance) -> AuditTimelineEntryResponse | None:
    """One synthesized entry for a terminal instance's own status —
    the only one of the six timeline sources that isn't a dedicated audit
    row anywhere, since WorkflowInstance.status is just a column, not an
    event log. Returns None for a non-terminal instance or a terminal one
    that (shouldn't happen, but defensively) has no completed_at yet."""
    outcome = _TERMINAL_OUTCOMES.get(instance.status)
    if outcome is None or instance.completed_at is None:
        return None

    metadata: dict[str, object] = {}
    if instance.status == InstanceStatus.FAILED:
        failed_step = _last_failed_step(instance)
        if failed_step is not None:
            metadata["failed_step_key"] = failed_step.step_key
            metadata["error_message"] = failed_step.error_message

    return AuditTimelineEntryResponse(
        timestamp=instance.completed_at,
        actor="System",
        actor_type="system",
        action=f"workflow_{instance.status.value}",
        resource_type="workflow_instance",
        resource_id=instance.id,
        workflow_instance_id=instance.id,
        workflow_name=instance.workflow_definition.name,
        outcome=outcome,
        metadata=metadata,
    )


def _manually_retried_entries(instance: WorkflowInstance) -> list[AuditTimelineEntryResponse]:
    """One synthesized entry per step that's ever been manually retried on
    this instance (Phase 13b) — same "read the live columns, no dedicated
    table" approach as `_terminal_entry`. Unlike `attempt_count` (which the
    engine's own automatic backoff retry also increments), `retried_at`/
    `retried_by_user_id` are set only by `retry_failed_step`, so every
    entry here really is a human intervention, never the engine's own
    retry-with-backoff. Only ever holds the most recent retry per step —
    a second manual retry of the same step overwrites the first's
    timestamp/actor, same known limitation as `_terminal_entry`'s single
    live status at this project's demo scale."""
    entries: list[AuditTimelineEntryResponse] = []
    for step in instance.step_instances:
        if step.retried_at is None:
            continue
        entries.append(
            AuditTimelineEntryResponse(
                timestamp=step.retried_at,
                actor=_user_name(step.retried_by) or "Unknown",
                actor_type="user",
                action="step_manually_retried",
                resource_type="workflow_step_instance",
                resource_id=step.id,
                workflow_instance_id=instance.id,
                workflow_name=instance.workflow_definition.name,
                outcome="retried",
                metadata={"step_key": step.step_key, "attempt_count": step.attempt_count},
            )
        )
    return entries


def build_audit_timeline(
    db: Session, *, workflow_instance_id: UUID | None = None, limit: int = 100
) -> list[AuditTimelineEntryResponse]:
    """Composes WorkflowEvent, ApprovalRequest/ApprovalDecision,
    AIExecution, MCPToolExecution, Notification, and WorkflowInstance's own
    terminal status into one chronological (oldest-first) feed. Backs both
    the Workflow Detail page's timeline (`workflow_instance_id` set) and
    the global Audit Log page (`workflow_instance_id=None`) — see this
    module's docstring for the global case's known scale limit.
    """
    entries: list[AuditTimelineEntryResponse] = []

    for event in workflow_event_repo.list_for_timeline(
        db, workflow_instance_id=workflow_instance_id, limit=limit
    ):
        instance = event.workflow_instance
        actor, actor_type = _actor(instance.initiated_by if instance else None)
        entries.append(
            AuditTimelineEntryResponse(
                timestamp=event.received_at,
                actor=actor,
                actor_type=actor_type,
                action="workflow_started",
                resource_type="workflow_instance",
                resource_id=event.workflow_instance_id,
                workflow_instance_id=event.workflow_instance_id,
                workflow_name=instance.workflow_definition.name if instance else None,
                outcome="started",
                metadata={"event_type": event.event_type},
            )
        )

    for approval in approval_request_repo.list_for_timeline(
        db, workflow_instance_id=workflow_instance_id, limit=limit
    ):
        workflow_name = approval.workflow_instance.workflow_definition.name
        entries.append(
            AuditTimelineEntryResponse(
                timestamp=approval.created_at,
                actor="System",
                actor_type="system",
                action="approval_requested",
                resource_type="approval_request",
                resource_id=approval.id,
                workflow_instance_id=approval.workflow_instance_id,
                workflow_name=workflow_name,
                outcome="pending",
                metadata={
                    "approver_role": approval.approver_role.value,
                    "assigned_to": _user_name(approval.assigned_user),
                    "step_key": approval.step_instance.step_key,
                },
            )
        )
        decision: ApprovalDecision
        for decision in approval.decisions:
            entries.append(
                AuditTimelineEntryResponse(
                    timestamp=decision.decided_at,
                    actor=_user_name(decision.decided_by) or "Unknown",
                    actor_type="user",
                    action=f"approval_{decision.decision.value}",
                    resource_type="approval_request",
                    resource_id=approval.id,
                    workflow_instance_id=approval.workflow_instance_id,
                    workflow_name=workflow_name,
                    outcome=decision.decision.value,
                    metadata={
                        "notes": decision.notes,
                        "step_key": approval.step_instance.step_key,
                    },
                )
            )

    for execution in ai_execution_repo.list_for_timeline(
        db, workflow_instance_id=workflow_instance_id, limit=limit
    ):
        entries.append(
            AuditTimelineEntryResponse(
                timestamp=execution.created_at,
                actor="AI",
                actor_type="ai",
                action=f"ai_call_{execution.status.value}",
                resource_type="ai_execution",
                resource_id=execution.id,
                workflow_instance_id=execution.workflow_instance_id,
                workflow_name=execution.workflow_instance.workflow_definition.name,
                outcome=execution.status.value,
                metadata={
                    "task_type": execution.task_type.value,
                    "confidence_score": execution.confidence_score,
                    "requires_human_review": execution.requires_human_review,
                    "step_key": execution.step_instance.step_key,
                },
            )
        )

    for mcp_execution in mcp_tool_execution_repo.list_for_timeline(
        db, workflow_instance_id=workflow_instance_id, limit=limit
    ):
        is_ai_agent = mcp_execution.caller == MCPToolCaller.AI_AGENT
        entries.append(
            AuditTimelineEntryResponse(
                timestamp=mcp_execution.created_at,
                actor="AI Agent" if is_ai_agent else "Workflow Engine",
                actor_type="ai" if is_ai_agent else "system",
                action=f"integration_call_{mcp_execution.status.value}",
                resource_type="mcp_tool_execution",
                resource_id=mcp_execution.id,
                workflow_instance_id=mcp_execution.workflow_instance_id,
                workflow_name=(
                    mcp_execution.workflow_instance.workflow_definition.name
                    if mcp_execution.workflow_instance
                    else None
                ),
                outcome=mcp_execution.status.value,
                metadata={
                    "tool_name": mcp_execution.tool_name,
                    "mock_mode": mcp_execution.mock_mode,
                },
            )
        )

    for notification in notification_repo.list_for_timeline(
        db, workflow_instance_id=workflow_instance_id, limit=limit
    ):
        entries.append(
            AuditTimelineEntryResponse(
                timestamp=notification.created_at,
                actor="System",
                actor_type="system",
                action=f"notification_{notification.status.value}",
                resource_type="notification",
                resource_id=notification.id,
                workflow_instance_id=notification.workflow_instance_id,
                workflow_name=(
                    notification.workflow_instance.workflow_definition.name
                    if notification.workflow_instance
                    else None
                ),
                outcome=notification.status.value,
                metadata={
                    "type": notification.type.value,
                    "channel": notification.channel.value,
                    "recipient": _user_name(notification.user),
                },
            )
        )

    if workflow_instance_id is not None:
        instance = workflow_instance_repo.get_by_id_with_relations(db, workflow_instance_id)
        if instance is not None:
            terminal = _terminal_entry(instance)
            if terminal is not None:
                entries.append(terminal)
            entries.extend(_manually_retried_entries(instance))
    else:
        all_instances = workflow_instance_repo.list_all(db)

        terminal_candidates = [
            i
            for i in all_instances
            if i.status in _TERMINAL_OUTCOMES and i.completed_at is not None
        ]
        terminal_instances = sorted(
            terminal_candidates, key=_completed_at_key, reverse=True
        )[:limit]
        for instance in terminal_instances:
            terminal = _terminal_entry(instance)
            if terminal is not None:
                entries.append(terminal)

        retried_candidates = [
            entry for i in all_instances for entry in _manually_retried_entries(i)
        ]
        retried_candidates.sort(key=lambda e: e.timestamp, reverse=True)
        entries.extend(retried_candidates[:limit])

    entries.sort(key=lambda e: e.timestamp)
    return entries
