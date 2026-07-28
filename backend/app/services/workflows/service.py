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

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import FailureBehavior, InstanceStatus, StepStatus, StepType, UserRole
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.repositories import (
    approval_request_repo,
    employee_repo,
    user_repo,
    workflow_definition_repo,
    workflow_event_repo,
    workflow_instance_repo,
    workflow_step_repo,
)
from app.schemas.workflow_definition import StepDefinition, WorkflowDefinitionSchema
from app.services.workflows.conditions import build_condition_context, evaluate_condition
from app.services.workflows.executors import (
    StepExecutionResult,
    execute_ai_action,
    execute_mcp_tool,
)
from app.services.workflows.state_machine import transition_instance, transition_step

# Matches the example schedule in integration-strategy.md (2s, 8s, 30s) —
# the last value repeats for any attempt beyond the list, so a step
# configured for more than 3 retries doesn't crash on a list index.
_BACKOFF_SCHEDULE_SECONDS = [2, 8, 30]


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
        existing_instance = workflow_instance_repo.get_by_id(
            db, existing_event.workflow_instance_id
        )
        if existing_instance is None:
            # The event row points at an instance that no longer exists —
            # a genuine data-integrity problem (e.g. manual deletion), not
            # a normal runtime path. Fail loudly here rather than returning
            # None from a function whose signature promises a real
            # WorkflowInstance, which would just surface as a confusing
            # AttributeError wherever the caller next touches the result.
            raise NotFoundError(
                f"workflow event with dedup_key '{dedup_key}' references "
                f"workflow instance '{existing_event.workflow_instance_id}', "
                "which no longer exists"
            )
        return existing_instance

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
        if step_row.status == StepStatus.WAITING_EXTERNAL:
            # Waiting on a Jira fulfillment webhook (ADR-0010) — nothing to
            # advance until confirm_external_completion resumes this step
            # directly. Not reachable via the worker's own poll query today
            # (list_ready_to_advance only selects PENDING-with-due-
            # scheduled_at steps for its waiting_external case), but this
            # guard is what makes that true by design rather than by
            # accident if a future caller ever calls advance_workflow on
            # such an instance.
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
            _create_approval_request(db, instance, step_row, step_def)
            return instance

        result = _execute(db, step_def, step_row, definition, instance, context)
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


def _create_approval_request(
    db: Session,
    instance: WorkflowInstance,
    step_row: WorkflowStepInstance,
    step_def: StepDefinition,
) -> None:
    """Called the moment a step pauses at waiting_approval — not upfront
    when the instance starts, so an approval step that a condition skips
    (e.g. it_review_access when the AI didn't flag review) never creates a
    row anyone would see in their inbox.

    Deliberately calls the repository directly rather than a
    services/approvals function — see docs/architecture/service-boundaries.md
    for why: services/approvals depends on this module (to call
    resume_workflow_step once a decision is made), so this module calling
    back into services/approvals would be circular. Creating a row is pure
    repository work with no business logic beyond `_resolve_approver`,
    which is why it can live here without needing the approvals service.
    """
    approval_config = step_def.approval
    if approval_config is None:
        # Guaranteed non-None for type == APPROVAL by
        # WorkflowDefinitionSchema's validator — this branch only exists to
        # satisfy the type checker, not because it can happen at runtime.
        raise ValueError(f"approval step '{step_def.key}' is missing its approval config")

    assigned_user_id = _resolve_approver(db, instance, approval_config.approver_role)
    approval_request_repo.create(
        db,
        workflow_instance_id=instance.id,
        step_instance_id=step_row.id,
        approver_role=approval_config.approver_role,
        assigned_user_id=assigned_user_id,
        sequence_order=approval_config.sequence_order,
    )


def _resolve_approver(
    db: Session, instance: WorkflowInstance, approver_role: UserRole
) -> UUID | None:
    """Manager approvals are assigned to the specific employee's actual
    manager (Employee.manager_id -> that manager's linked User account),
    when one exists — approving your own team's onboarding shouldn't be
    something any random manager in the company can pick up. Every other
    role (IT, Security) has no natural single owner in this data model, so
    those stay a role-based pool: assigned_user_id=None, visible to anyone
    with that role via approval_request_repo.list_pending_for_user.
    """
    if approver_role != UserRole.MANAGER or instance.employee_id is None:
        return None
    employee = employee_repo.get_by_id(db, instance.employee_id)
    if employee is None or employee.manager_id is None:
        return None
    manager_user = user_repo.get_by_employee_id(db, employee.manager_id)
    return manager_user.id if manager_user else None


def _execute(
    db: Session,
    step_def: StepDefinition,
    step_row: WorkflowStepInstance,
    definition: WorkflowDefinitionSchema,
    instance: WorkflowInstance,
    context: dict[str, Any],
) -> StepExecutionResult:
    if step_def.type == StepType.VALIDATION:
        return _execute_validation(definition, instance)
    if step_def.type == StepType.AI_ACTION:
        return execute_ai_action(db, step_def, step_row, instance, context)
    if step_def.type == StepType.MCP_TOOL:
        return execute_mcp_tool(db, step_def, step_row, instance, context)
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
        if result.awaiting_external_ref:
            # ADR-0010: a successful create_jira_task call on a step flagged
            # awaits_fulfillment doesn't complete the step yet — it pauses,
            # holding the issue key, until /webhooks/jira confirms the
            # ticket reached Done (see confirm_external_completion below).
            step_row.external_ref = result.awaiting_external_ref
            transition_step(step_row, StepStatus.WAITING_EXTERNAL)
            transition_instance(instance, InstanceStatus.WAITING_EXTERNAL)
            db.commit()
            return
        step_row.completed_at = _utcnow()
        transition_step(step_row, StepStatus.COMPLETED)
        db.commit()
        return

    step_row.error_message = result.error_message
    if result.output_data is not None:
        # A failed step can still carry safe fallback output — e.g. the AI
        # service defaulting requires_human_review=True when it couldn't
        # produce a real recommendation (no API key, network error, bad
        # response). Without this, a downstream step whose condition reads
        # this step's output (recommend_access.requires_human_review) would
        # raise ConditionEvaluationError over a step that simply never
        # completed, instead of safely routing to a human. Every other
        # failure path never populates output_data, so this is a no-op for
        # them — only services/ai/service.py's graceful-fallback path uses
        # it today.
        step_row.output_data = result.output_data
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
    """The generic pause/resume half of "human-in-the-loop." Called from
    two places: `services/approvals/service.py::decide()` for real approval
    decisions (Phase 7), and directly from workflow-engine tests (Phase 6)
    that simulate a decision without going through the approvals layer at
    all — both are valid callers, this function doesn't know or care which.
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


def confirm_external_completion(
    db: Session, instance: WorkflowInstance, step_row: WorkflowStepInstance
) -> WorkflowInstance:
    """The fulfillment counterpart to resume_workflow_step (ADR-0010): called
    by api/routes/webhooks.py once a Jira webhook confirms the issue this
    step created reached Done. Same pause/resume shape as an approval —
    step and instance both come out of a waiting state and the engine
    advances to whatever's next — just triggered by an external system
    event instead of a human decision.

    Raises ConflictError if this step isn't currently WAITING_EXTERNAL,
    which is also this function's idempotency guard: the webhook route
    checks step status itself before calling this (so a duplicate Jira
    delivery gets a benign 200, not a 409 that trains Jira to keep
    retrying) — this raise is a defense-in-depth backstop for any other
    caller, not the primary duplicate-delivery handling.
    """
    if step_row.status != StepStatus.WAITING_EXTERNAL or instance.status != (
        InstanceStatus.WAITING_EXTERNAL
    ):
        raise ConflictError(
            "This step is not currently waiting on an external fulfillment "
            f"confirmation (step status: {step_row.status.value}, instance "
            f"status: {instance.status.value})."
        )

    step_row.output_data = {**(step_row.output_data or {}), "fulfillment_confirmed": True}
    step_row.completed_at = _utcnow()
    transition_step(step_row, StepStatus.COMPLETED)
    transition_instance(instance, InstanceStatus.RUNNING)
    db.commit()
    return advance_workflow(db, instance)
