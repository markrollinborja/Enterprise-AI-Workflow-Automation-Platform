"""The workflow execution engine: start an instance, advance it through its
steps in order, pause it for a human approval, resume it once a decision is
recorded. Every status write goes through state_machine.py's
transition_instance/transition_step — this module never sets `.status`
directly, which is what guarantees a bad transition raises instead of
silently corrupting a running workflow.

Two entry points call `advance_workflow`, and only one of them is "the
engine": `start_workflow` calls it once synchronously right after creating
an instance (so a demo doesn't wait on a poll tick for the easy steps), and
`app/workers/runner.py` calls it on a timer for instances stuck in
`waiting_external` whose retry is due. Same function either way — see
ADR-0002's "the worker is a scheduler, not a second implementation."
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import FailureBehavior, InstanceStatus, StepStatus, StepType
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.repositories import (
    workflow_definition_repo,
    workflow_event_repo,
    workflow_instance_repo,
    workflow_step_repo,
)
from app.schemas.workflow_definition import StepDefinition, WorkflowDefinitionSchema
from app.services.workflows.conditions import build_condition_context, evaluate_condition
from app.services.workflows.executors import (
    StepExecutionResult,
    execute_ai_action_stub,
    execute_mcp_tool_stub,
)
from app.services.workflows.state_machine import transition_instance, transition_step

# Matches the example schedule in integration-strategy.md (2s, 8s, 30s) —
# the last value repeats for any attempt beyond the list, so a step
# configured for more than 3 retries doesn't crash on a list index.
_BACKOFF_SCHEDULE_SECONDS = [2, 8, 30]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _backoff_seconds(attempt_count: int) -> int:
    index = min(max(attempt_count - 1, 0), len(_BACKOFF_SCHEDULE_SECONDS) - 1)
    return _BACKOFF_SCHEDULE_SECONDS[index]


def start_workflow(
    db: Session,
    *,
    workflow_key: str,
    input_data: dict[str, Any],
    dedup_key: str,
    event_type: str | None = None,
    initiated_by_user_id: UUID | None = None,
    employee_id: UUID | None = None,
) -> WorkflowInstance:
    """Starts a workflow instance, or returns the existing one if
    `dedup_key` has already been used — see WorkflowEvent's docstring.
    Creates every WorkflowStepInstance row up front (all `pending`), then
    calls `advance_workflow` once before returning.
    """
    existing_event = workflow_event_repo.get_by_dedup_key(db, dedup_key)
    if existing_event is not None and existing_event.workflow_instance_id is not None:
        return workflow_instance_repo.get_by_id(db, existing_event.workflow_instance_id)

    definition_row = workflow_definition_repo.get_active_by_key(db, workflow_key)
    if definition_row is None:
        raise NotFoundError(f"no active workflow definition for key '{workflow_key}'")
    definition = WorkflowDefinitionSchema.model_validate(definition_row.definition_json)

    instance = workflow_instance_repo.create(
        db,
        workflow_definition_id=definition_row.id,
        status=InstanceStatus.PENDING,
        input_data=input_data,
        initiated_by_user_id=initiated_by_user_id,
        employee_id=employee_id,
        started_at=_utcnow(),
    )
    transition_instance(instance, InstanceStatus.RUNNING)
    db.commit()

    for step_def in definition.steps:
        workflow_step_repo.create(
            db,
            workflow_instance_id=instance.id,
            step_key=step_def.key,
            step_type=step_def.type,
            status=StepStatus.PENDING,
        )

    workflow_event_repo.create(
        db,
        event_type=event_type or f"{workflow_key}.started",
        payload=input_data,
        dedup_key=dedup_key,
        workflow_instance_id=instance.id,
    )

    return advance_workflow(db, instance)


def advance_workflow(db: Session, instance: WorkflowInstance) -> WorkflowInstance:
    """Runs steps, in definition order, until the instance completes, fails,
    pauses for approval, or starts waiting on a scheduled retry. Safe to
    call on an instance that isn't actually advanceable (e.g. already
    `completed`) — it's a no-op in that case, which is what lets the worker
    call this unconditionally on every instance it polls without needing
    its own "is this instance actually ready" branch beyond the query that
    selected it.
    """
    if instance.status not in (InstanceStatus.RUNNING, InstanceStatus.WAITING_EXTERNAL):
        return instance

    definition = WorkflowDefinitionSchema.model_validate(
        instance.workflow_definition.definition_json
    )
    steps_by_key: dict[str, WorkflowStepInstance] = {
        row.step_key: row for row in instance.step_instances
    }

    if instance.status == InstanceStatus.WAITING_EXTERNAL:
        transition_instance(instance, InstanceStatus.RUNNING)
        db.commit()

    for step_def in definition.steps:
        step_row = steps_by_key[step_def.key]

        if step_row.status in (StepStatus.COMPLETED, StepStatus.SKIPPED):
            continue
        if step_row.status in (StepStatus.WAITING_APPROVAL, StepStatus.REJECTED):
            # Waiting on a human, or already rejected (instance should
            # already be terminal in the latter case) — nothing to advance.
            return instance
        if step_row.status == StepStatus.FAILED:
            # Reached via failure_behavior=continue on an earlier pass —
            # already resolved (permanently failed, not retried), move on.
            continue

        # step_row.status == PENDING from here on: either fresh, or a
        # retry whose scheduled_at may or may not be due yet.
        if step_row.scheduled_at is not None and step_row.scheduled_at > _utcnow():
            transition_instance(instance, InstanceStatus.WAITING_EXTERNAL)
            db.commit()
            return instance

        context = build_condition_context(instance, steps_by_key.values())
        if step_def.condition is not None and not evaluate_condition(
            step_def.condition, context
        ):
            transition_step(step_row, StepStatus.SKIPPED)
            db.commit()
            continue

        transition_step(step_row, StepStatus.RUNNING)
        step_row.attempt_count += 1
        step_row.started_at = _utcnow()
        instance.current_step_key = step_row.step_key
        db.commit()

        if step_def.type == StepType.APPROVAL:
            transition_step(step_row, StepStatus.WAITING_APPROVAL)
            transition_instance(instance, InstanceStatus.WAITING_APPROVAL)
            db.commit()
            return instance

        result = _execute(step_def, step_row, definition, instance, context)
        _apply_step_result(db, instance, step_row, step_def, result)

        if step_row.status == StepStatus.COMPLETED:
            continue
        # FAILED with failure_behavior=continue: the loop keeps going.
        if step_row.status == StepStatus.FAILED and step_def.failure_behavior == (
            FailureBehavior.CONTINUE
        ):
            continue
        # Anything else (PENDING-for-retry, or FAILED that took down the
        # instance) means advance_workflow has nothing more to do right now.
        return instance

    transition_instance(instance, InstanceStatus.COMPLETED)
    instance.completed_at = _utcnow()
    instance.current_step_key = None
    db.commit()
    return instance


def _execute(
    step_def: StepDefinition,
    step_row: WorkflowStepInstance,
    definition: WorkflowDefinitionSchema,
    instance: WorkflowInstance,
    context: dict[str, Any],
) -> StepExecutionResult:
    if step_def.type == StepType.VALIDATION:
        return _execute_validation(definition, instance)
    if step_def.type == StepType.AI_ACTION:
        return execute_ai_action_stub(step_def, context)
    if step_def.type == StepType.MCP_TOOL:
        return execute_mcp_tool_stub(step_def, step_row, context)
    raise ValueError(f"unhandled step type in _execute: {step_def.type}")


def _execute_validation(
    definition: WorkflowDefinitionSchema, instance: WorkflowInstance
) -> StepExecutionResult:
    missing = [
        field
        for field, requirement in definition.input_schema.items()
        if requirement == "required" and field not in instance.input_data
    ]
    if missing:
        return StepExecutionResult(
            status="failed",
            error_message=f"missing required input field(s): {', '.join(sorted(missing))}",
        )
    return StepExecutionResult(status="completed", output_data={"valid": True})


def _apply_step_result(
    db: Session,
    instance: WorkflowInstance,
    step_row: WorkflowStepInstance,
    step_def: StepDefinition,
    result: StepExecutionResult,
) -> None:
    if result.status == "completed":
        step_row.output_data = result.output_data
        step_row.completed_at = _utcnow()
        transition_step(step_row, StepStatus.COMPLETED)
        db.commit()
        return

    step_row.error_message = result.error_message
    if (
        step_def.failure_behavior == FailureBehavior.RETRY
        and step_row.attempt_count < step_def.max_attempts
    ):
        transition_step(step_row, StepStatus.PENDING)
        step_row.scheduled_at = _utcnow() + timedelta(
            seconds=_backoff_seconds(step_row.attempt_count)
        )
        transition_instance(instance, InstanceStatus.WAITING_EXTERNAL)
        db.commit()
        return

    transition_step(step_row, StepStatus.FAILED)
    if step_def.failure_behavior != FailureBehavior.CONTINUE:
        transition_instance(instance, InstanceStatus.FAILED)
        instance.completed_at = _utcnow()
    db.commit()


def resume_workflow_step(
    db: Session,
    instance: WorkflowInstance,
    step_row: WorkflowStepInstance,
    *,
    decision: Literal["approved", "rejected"],
    notes: str | None = None,
) -> WorkflowInstance:
    """The generic pause/resume half of "human-in-the-loop" — Phase 7's
    actual ApprovalRequest/ApprovalDecision models and routes will call
    this once a real decision is recorded. Tested directly here (simulating
    what Phase 7 will do) so pause/resume is proven correct before Phase 7
    exists to exercise it for real.
    """
    if step_row.status != StepStatus.WAITING_APPROVAL or instance.status != (
        InstanceStatus.WAITING_APPROVAL
    ):
        raise ConflictError(
            "This step is not currently waiting for an approval decision "
            f"(step status: {step_row.status.value}, instance status: {instance.status.value})."
        )

    step_row.output_data = {"decision": decision, "notes": notes}
    step_row.completed_at = _utcnow()

    if decision == "approved":
        transition_step(step_row, StepStatus.COMPLETED)
        transition_instance(instance, InstanceStatus.RUNNING)
        db.commit()
        return advance_workflow(db, instance)

    transition_step(step_row, StepStatus.REJECTED)
    transition_instance(instance, InstanceStatus.REJECTED)
    instance.completed_at = _utcnow()
    db.commit()
    return instance
