"""execute_ai_action calls the real AI service (Phase 9, services/ai).
execute_mcp_tool calls the real MCP server (Phase 10, mcp_server/ +
services/integrations/mcp_client.py) — what used to be
execute_mcp_tool_stub. Both are the deliberate seam this module has always
been: the engine (`service.py`) doesn't know or care whether a step's
result came from a stub or a real integration, and the
retry/backoff/waiting_external machinery is exercised identically either
way.

execute_mcp_tool still reads a test hook from the workflow instance's own
input_data — the `force_failure` hook integration-strategy.md calls for,
built one phase before the real integration it applies to and preserved
unchanged here on purpose:

- `force_failure_steps`: list[str] of step_keys that should report a
  simulated failure (once, or every time — see execute_mcp_tool). Checked
  *before* the real MCP client is ever invoked, so the entire
  retry-and-recover demo scenario (Phase 6) still runs with zero real
  network calls, exactly as it did against the stub.

The equivalent `ai_requires_review` hook execute_ai_action_stub used to
read is gone — a real ai_action step's requires_human_review now comes
from the AI service's actual (or mocked, in tests) confidence score, not
an input flag. See services/ai/service.py and tests/test_ai_service.py.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.employee import Employee
from app.models.enums import MCPToolCaller
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.repositories import application_repo, employee_repo
from app.schemas.workflow_definition import StepDefinition
from app.services.ai import service as ai_service
from app.services.integrations import mcp_client
from app.services.integrations.mcp_client import MCPToolError


@dataclass
class StepExecutionResult:
    status: Literal["completed", "failed"]
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    # Set only by execute_mcp_tool, only when step_def.awaits_fulfillment is
    # true and the call succeeded (ADR-0010, Phase 10 checkpoint 3): the
    # Jira issue key /webhooks/jira will later look this step up by.
    # service.py's _apply_step_result reads this to decide WAITING_EXTERNAL
    # vs. COMPLETED — every other step type/config leaves this None and
    # behaves exactly as before.
    awaiting_external_ref: str | None = None


class MCPArgumentError(Exception):
    """Raised when this step's own data can't support building a tool call
    (e.g. no employee linked to this workflow instance) — a workflow-data
    problem, distinct from MCPToolError (a transport/tool-execution
    problem), so a failure here reads clearly as "this step's inputs were
    wrong" rather than "the MCP server rejected something.\""""


def execute_ai_action(
    db: Session,
    step_def: StepDefinition,
    step_row: WorkflowStepInstance,
    instance: WorkflowInstance,
    context: dict[str, Any],
) -> StepExecutionResult:
    """Thin dispatcher: looks up which structured task this step names
    (`ai_task`, required for every ai_action step — see
    schemas/workflow_definition.py's validator) and translates
    services/ai/service.py's AIActionResult into this module's
    StepExecutionResult. All the actual AI logic — prompting, calling
    OpenAI, confidence thresholds, the AIExecution audit row — lives in
    services/ai, not here; see that module's docstring for why."""
    if not step_def.ai_task:
        raise ValueError(f"ai_action step '{step_def.key}' is missing 'ai_task'")
    result = ai_service.execute_ai_task(
        db,
        ai_task=step_def.ai_task,
        step_row=step_row,
        instance=instance,
        context=context,
        requires_review_enabled=step_def.requires_review,
    )
    return StepExecutionResult(
        status=result.status, output_data=result.output_data, error_message=result.error_message
    )


def execute_mcp_tool(
    db: Session,
    step_def: StepDefinition,
    step_row: WorkflowStepInstance,
    instance: WorkflowInstance,
    context: dict[str, Any],
) -> StepExecutionResult:
    """Builds this step's tool arguments from workflow context, calls the
    named tool through services/integrations/mcp_client.py (which owns the
    real MCP protocol call, the MCPToolExecution audit row, and — per
    ADR-0012 — does not retry internally), and translates the result into a
    StepExecutionResult. All the actual tool logic (mock/real mode, Jira/
    Slack/Calendar specifics) lives in mcp_server/, not here."""
    force_failure_steps = context["input"].get("force_failure_steps", [])
    if step_def.key in force_failure_steps:
        return StepExecutionResult(
            status="failed",
            error_message=(
                f"Simulated failure for step '{step_def.key}' "
                f"(force_failure_steps test hook, attempt {step_row.attempt_count})."
            ),
        )

    if not step_def.mcp_tool:
        raise ValueError(f"mcp_tool step '{step_def.key}' is missing 'mcp_tool'")

    try:
        arguments = _build_mcp_tool_arguments(db, step_def, instance, context)
    except MCPArgumentError as exc:
        return StepExecutionResult(status="failed", error_message=str(exc))

    try:
        result = mcp_client.call_tool(
            db,
            tool_name=step_def.mcp_tool,
            arguments=arguments,
            caller=MCPToolCaller.WORKFLOW_ENGINE,
            workflow_instance_id=instance.id,
            step_instance_id=step_row.id,
        )
    except MCPToolError as exc:
        return StepExecutionResult(status="failed", error_message=str(exc))

    awaiting_ref = result.get("issue_key") if step_def.awaits_fulfillment else None
    return StepExecutionResult(
        status="completed", output_data=result, awaiting_external_ref=awaiting_ref
    )


def _build_mcp_tool_arguments(
    db: Session, step_def: StepDefinition, instance: WorkflowInstance, context: dict[str, Any]
) -> dict[str, Any]:
    """Dispatches on the step's own key, not just its mcp_tool name — both
    V1 workflows' create-a-Jira-task steps call the same generic
    create_jira_task tool (see ADR-0012's naming note), but need genuinely
    different summaries/descriptions built from different context. This is
    where that per-workflow content decision lives, deliberately outside
    mcp_server/ (mcp_server doesn't know which workflow is calling it, and
    shouldn't have to)."""
    if step_def.key == "create_it_tasks":
        employee = _require_employee(db, instance)
        recommendation = context.get("recommend_access") or {}
        package_name = recommendation.get("recommended_package_name", "pending IT review")
        return {
            "project_key": "ONB",
            "summary": f"Onboarding tasks: {employee.first_name} {employee.last_name}",
            "description": (
                f"New hire onboarding for {employee.job_title} in "
                f"{employee.department.name}. Recommended access package: {package_name}."
            ),
            "issue_type": "Task",
        }

    if step_def.key == "schedule_orientation":
        employee = _require_employee(db, instance)
        start_time = datetime.combine(employee.start_date, time(9, 0), tzinfo=UTC)
        return {
            "summary": f"Orientation: {employee.first_name} {employee.last_name}",
            "description": (
                f"New hire orientation for {employee.job_title}, {employee.department.name}."
            ),
            "start_time_iso": start_time.isoformat(),
            "duration_minutes": 60,
            "attendee_emails": [employee.work_email],
        }

    if step_def.key == "notify_slack":
        employee = _require_employee(db, instance)
        recommendation = context.get("recommend_access") or {}
        package_name = recommendation.get("recommended_package_name", "pending IT review")
        return {
            "channel": "#onboarding",
            "message": (
                f"{employee.first_name} {employee.last_name} has completed onboarding. "
                f"Access package: {package_name}."
            ),
        }

    if step_def.key == "create_fulfillment_task":
        employee = _require_employee(db, instance)
        application = _require_application(db, instance)
        return {
            "project_key": "ACC",
            "summary": (
                f"Access request: {application.name} for "
                f"{employee.first_name} {employee.last_name}"
            ),
            "description": (
                f"Risk level: {instance.input_data.get('application_risk_level')}. "
                f"Justification: {instance.input_data.get('justification', '')}"
            ),
            "issue_type": "Task",
        }

    if step_def.key == "notify_employee":
        employee = _require_employee(db, instance)
        application = _require_application(db, instance)
        return {
            # Real-mode limitation, noted rather than hidden: Slack DM
            # addressing needs a user ID, not an email — real mode would
            # need a users.lookupByEmail call first. Out of scope for V1;
            # mock mode doesn't care, and this is a known gap, not a bug.
            "channel": f"@{employee.work_email}",
            "message": (
                f"Your access request for {application.name} has been approved "
                "and is being fulfilled."
            ),
        }

    raise MCPArgumentError(f"no argument-building logic for mcp_tool step '{step_def.key}'")


def _require_employee(db: Session, instance: WorkflowInstance) -> Employee:
    if instance.employee_id is None:
        raise MCPArgumentError("this workflow instance has no linked employee")
    employee = employee_repo.get_by_id(db, instance.employee_id)
    if employee is None:
        raise MCPArgumentError("no employee record found for this workflow instance")
    return employee


def _require_application(db: Session, instance: WorkflowInstance) -> Application:
    application_id = instance.input_data.get("application_id")
    if not application_id:
        raise MCPArgumentError("this workflow instance has no application_id in its input_data")
    application = application_repo.get_by_id(db, UUID(application_id))
    if application is None:
        raise MCPArgumentError(f"no application found for id {application_id!r}")
    return application
