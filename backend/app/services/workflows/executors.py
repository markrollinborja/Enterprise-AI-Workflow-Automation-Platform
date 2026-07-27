"""execute_ai_action calls the real AI service (Phase 9, services/ai) —
what used to be execute_ai_action_stub. execute_mcp_tool_stub is still a
stub: the real MCP server doesn't exist until Phase 10. Both are the
deliberate seam this module has always been: the engine (`service.py`)
doesn't know or care whether a step's result came from a stub or a real
integration, and the retry/backoff/waiting_external machinery is exercised
identically either way.

execute_mcp_tool_stub still reads a test hook from the workflow instance's
own input_data — the `force_failure` hook integration-strategy.md calls
for, built one phase earlier than the real integration it applies to:

- `force_failure_steps`: list[str] of step_keys that should report a
  simulated failure (once, or every time — see execute_mcp_tool_stub).
  This is what let Phase 6 build and test the entire retry-and-recover
  demo scenario before a real Jira/Slack/Calendar call exists to fail.

The equivalent `ai_requires_review` hook execute_ai_action_stub used to
read is gone — a real ai_action step's requires_human_review now comes
from the AI service's actual (or mocked, in tests) confidence score, not
an input flag. See services/ai/service.py and tests/test_ai_service.py.
"""

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.schemas.workflow_definition import StepDefinition
from app.services.ai import service as ai_service


@dataclass
class StepExecutionResult:
    status: Literal["completed", "failed"]
    output_data: dict[str, Any] | None = None
    error_message: str | None = None


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


def execute_mcp_tool_stub(
    step_def: StepDefinition, step_row: WorkflowStepInstance, context: dict[str, Any]
) -> StepExecutionResult:
    """Real version (Phase 10): call the named MCP tool through the
    integrations service (retry/backoff/audit wrapper), get back a typed
    result. Until then: succeeds with placeholder output naming the tool
    that would have been called — unless this step's key is listed in the
    workflow's `force_failure_steps` input, in which case it reports a
    simulated failure so the engine's retry_behavior handling (see
    service.py) has something real to exercise."""
    force_failure_steps = context["input"].get("force_failure_steps", [])
    if step_def.key in force_failure_steps:
        return StepExecutionResult(
            status="failed",
            error_message=(
                f"Simulated failure for step '{step_def.key}' "
                f"(force_failure_steps test hook, attempt {step_row.attempt_count})."
            ),
        )
    return StepExecutionResult(
        status="completed",
        output_data={
            "stub": True,
            "note": f"MCP tool '{step_def.mcp_tool}' not implemented until Phase 10",
        },
    )
