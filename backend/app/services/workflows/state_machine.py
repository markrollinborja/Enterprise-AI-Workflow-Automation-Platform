"""The transition tables from docs/architecture/workflow-state-model.md,
made real and enforced. Nothing outside this module should ever write to
`WorkflowInstance.status` or `WorkflowStepInstance.status` directly — going
through `transition_instance` / `transition_step` is what guarantees an
invalid change (resuming a rejected workflow, completing an instance with a
pending approval) raises instead of silently corrupting state.

Pure and side-effect-free apart from mutating the passed-in object's
`.status` — no DB session, no I/O, so this is trivially unit-testable
without any fixtures (see tests/test_state_machine.py).
"""

from app.core.exceptions import AppError
from app.models.enums import InstanceStatus, StepStatus
from app.models.workflow import WorkflowInstance, WorkflowStepInstance


class InvalidTransitionError(AppError):
    status_code = 409

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Cannot transition from '{current}' to '{target}'.")


INSTANCE_TRANSITIONS: dict[InstanceStatus, set[InstanceStatus]] = {
    InstanceStatus.PENDING: {InstanceStatus.RUNNING, InstanceStatus.CANCELLED},
    InstanceStatus.RUNNING: {
        InstanceStatus.WAITING_APPROVAL,
        InstanceStatus.WAITING_EXTERNAL,
        InstanceStatus.COMPLETED,
        InstanceStatus.FAILED,
        InstanceStatus.CANCELLED,
    },
    InstanceStatus.WAITING_APPROVAL: {
        InstanceStatus.RUNNING,
        InstanceStatus.REJECTED,
        InstanceStatus.CANCELLED,
    },
    InstanceStatus.WAITING_EXTERNAL: {
        InstanceStatus.RUNNING,
        InstanceStatus.FAILED,
        InstanceStatus.CANCELLED,
    },
    # Terminal — no code path may move an instance out of these.
    InstanceStatus.COMPLETED: set(),
    InstanceStatus.FAILED: set(),
    InstanceStatus.REJECTED: set(),
    InstanceStatus.CANCELLED: set(),
}

STEP_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.SKIPPED},
    StepStatus.RUNNING: {
        StepStatus.COMPLETED,
        StepStatus.FAILED,
        StepStatus.WAITING_APPROVAL,
        # A successful mcp_tool call on a step flagged awaits_fulfillment
        # (ADR-0010, Phase 10 checkpoint 3) — the Jira ticket exists but
        # isn't confirmed done yet.
        StepStatus.WAITING_EXTERNAL,
        # Transient failure with retries left re-enters PENDING on the same
        # row (attempt_count += 1) rather than creating a new one.
        StepStatus.PENDING,
    },
    StepStatus.WAITING_APPROVAL: {StepStatus.COMPLETED, StepStatus.REJECTED},
    # Only COMPLETED for V1 — /webhooks/jira only reacts to the ticket
    # reaching "Done" (see the route's docstring). Treating some other
    # Jira status transition as a step failure is a real V2 feature
    # (escalation/cancellation semantics), not a gap in this table.
    StepStatus.WAITING_EXTERNAL: {StepStatus.COMPLETED},
    # Terminal for that step. Whether the *workflow* fails, continues, or
    # retries from here is a definition-level failure_behavior decision the
    # Phase 6 engine makes — not something this table encodes.
    StepStatus.COMPLETED: set(),
    StepStatus.FAILED: set(),
    StepStatus.SKIPPED: set(),
    StepStatus.REJECTED: set(),
}


def transition_instance(instance: WorkflowInstance, target: InstanceStatus) -> None:
    if target not in INSTANCE_TRANSITIONS[instance.status]:
        raise InvalidTransitionError(instance.status.value, target.value)
    instance.status = target


def transition_step(step: WorkflowStepInstance, target: StepStatus) -> None:
    if target not in STEP_TRANSITIONS[step.status]:
        raise InvalidTransitionError(step.status.value, target.value)
    step.status = target
