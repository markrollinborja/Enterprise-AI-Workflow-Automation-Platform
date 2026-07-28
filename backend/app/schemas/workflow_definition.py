"""The schema that every workflows/*.json file is validated against.

This is what ADR-0003 means by "definition_json's schema is the contract" —
designed here, not copied from the spec's illustrative example (the spec
explicitly says not to use that example blindly). Loading a workflow file
that doesn't match this shape fails at seed time with a clear Pydantic
error, not at 2am mid-workflow with a KeyError three layers deep.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import FailureBehavior, StepType, TriggerType, UserRole


class ApprovalStepConfig(BaseModel):
    """Required on (and only on) a step with type == approval."""

    approver_role: UserRole
    # Chains multiple approval steps into a sequence — manager (1), then IT
    # (2), then security (3). Two steps sharing a sequence_order would mean
    # "either approves, both unblock the same gate," which no V1 workflow
    # needs; the engine (Phase 6) treats sequence_order as a strict order.
    sequence_order: int = Field(default=1, ge=1)


class StepDefinition(BaseModel):
    key: str
    name: str
    type: StepType
    # A small comparison expression evaluated against the workflow's
    # input_data and prior steps' output_data (e.g.
    # "application.risk_level == 'high'"). None means "always run." The
    # *evaluator* is Phase 6 — deliberately not a Python eval() sandbox, see
    # docs/decisions for why arbitrary code execution is a non-goal.
    condition: str | None = None
    approval: ApprovalStepConfig | None = None
    # ai_action only: whether this step's result can require human review at
    # all. When True, services/ai/service.py computes a real
    # requires_human_review flag from the model's self-reported confidence
    # score (below threshold -> True); when False, the task never gates on
    # confidence and requires_human_review is always False, regardless of
    # what the model reports. Meaningless on non-ai_action steps. (This
    # field existed since Phase 6 but the stub executor never actually read
    # it — Phase 9 is what wires it up for real.)
    requires_review: bool = False
    # ai_action only: which structured task services/ai/service.py should
    # run for this step (e.g. "recommend_access_package"). See AITaskType.
    ai_task: str | None = None
    # mcp_tool only: the tool name the engine calls (see
    # docs/architecture/mcp-architecture.md for the registered tool names).
    mcp_tool: str | None = None
    # mcp_tool + create_jira_task only (ADR-0010, Phase 10 checkpoint 3):
    # when true, a successful call doesn't complete this step — it moves to
    # WAITING_EXTERNAL holding the created issue's key, and only reaches
    # COMPLETED once /webhooks/jira confirms that issue transitioned to
    # Done. False (the default) preserves every other mcp_tool step's
    # existing behavior: success completes the step immediately.
    awaits_fulfillment: bool = False
    failure_behavior: FailureBehavior = FailureBehavior.FAIL_WORKFLOW
    # Only meaningful when failure_behavior == retry.
    max_attempts: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _require_type_specific_fields(self) -> "StepDefinition":
        if self.type == StepType.APPROVAL and self.approval is None:
            raise ValueError(f"step '{self.key}': type=approval requires an 'approval' config")
        if self.type == StepType.AI_ACTION and not self.ai_task:
            raise ValueError(f"step '{self.key}': type=ai_action requires 'ai_task'")
        if self.type == StepType.MCP_TOOL and not self.mcp_tool:
            raise ValueError(f"step '{self.key}': type=mcp_tool requires 'mcp_tool'")
        if self.failure_behavior == FailureBehavior.RETRY and self.max_attempts <= 1:
            raise ValueError(
                f"step '{self.key}': failure_behavior=retry needs max_attempts > 1"
            )
        if self.awaits_fulfillment and self.mcp_tool != "create_jira_task":
            raise ValueError(
                f"step '{self.key}': awaits_fulfillment is only meaningful for "
                "mcp_tool='create_jira_task' (its output is the only one carrying "
                "an issue_key to correlate a webhook against)"
            )
        return self


class WorkflowDefinitionSchema(BaseModel):
    workflow_key: str
    name: str
    description: str
    trigger_type: TriggerType
    # Required when trigger_type == event (e.g. "employee.created"); None
    # for manual triggers, which start from an explicit user action instead.
    trigger_event: str | None = None
    version: int = Field(default=1, ge=1)
    # Flat and shallow on purpose — {"employee_id": "required"} — not a full
    # JSON Schema document. A "validation" step checks presence against
    # this; nothing here needs draft-07 keyword support for two workflows.
    input_schema: dict[str, Literal["required", "optional"]]
    steps: list[StepDefinition]
    # Reserved for future branching support (see Phase 6 non-goals) — one
    # allowed value today because V1 has no parallel/partial-completion
    # paths, not because the field is decorative.
    completion_criteria: Literal["all_steps_completed"] = "all_steps_completed"

    @model_validator(mode="after")
    def _validate_cross_field_rules(self) -> "WorkflowDefinitionSchema":
        if self.trigger_type == TriggerType.EVENT and not self.trigger_event:
            raise ValueError("trigger_type=event requires 'trigger_event'")
        if not self.steps:
            raise ValueError("a workflow must have at least one step")
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("step keys must be unique within a workflow")
        return self
