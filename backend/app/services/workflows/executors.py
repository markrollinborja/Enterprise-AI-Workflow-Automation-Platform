"""Stub executors for the two step types this project can't actually
perform yet: `ai_action` (needs the AI service, Phase 9) and `mcp_tool`
(needs the MCP server, Phase 10). Both are a deliberate seam — Phase 9/10
replace the *inside* of these two functions with a real OpenAI call and a
real MCP client call respectively. Nothing else changes: the engine
(`service.py`) doesn't know or care whether a step's result came from a
stub or the real integration, and the retry/backoff/waiting_external
machinery is exercised identically either way.

Both stubs read a test hook from the workflow instance's own input_data
rather than needing a separate "test mode" concept — this is the
`force_failure` hook integration-strategy.md already calls for, just built
one phase earlier than the real integration it will eventually apply to:

- `force_failure_steps`: list[str] of step_keys that should report a
  simulated failure (once, or every time — see execute_mcp_tool_stub).
  This is what lets Phase 6 build and test the entire retry-and-recover
  demo scenario before a real Jira/Slack/Calendar call exists to fail.
- `ai_requires_review`: bool, defaults to True. Controls what the AI
  stub's `requires_human_review` output is — defaulting to True (rather
  than False) is a deliberate safe default: an unimplemented AI step
  should never cause a downstream human-review gate to silently skip.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.models.workflow import WorkflowStepInstance
from app.schemas.workflow_definition import StepDefinition


@dataclass
class StepExecutionResult:
    status: Literal["completed", "failed"]
    output_data: dict[str, Any] | None = None
    error_message: str | None = None


def execute_ai_action_stub(
    step_def: StepDefinition, context: dict[str, Any]
) -> StepExecutionResult:
    """Real version (Phase 9): build a prompt, call OpenAI, validate the
    response against a Pydantic schema, compute a genuine confidence score.
    Until then: always succeeds with placeholder output clearly marked as
    a stub, so a workflow that reaches an ai_action step can still
    complete end to end today."""
    requires_review = bool(context["input"].get("ai_requires_review", True))
    return StepExecutionResult(
        status="completed",
        output_data={
            "stub": True,
            "note": "AI service not implemented until Phase 9",
            "requires_human_review": requires_review,
        },
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
