"""Exercises every entry in INSTANCE_TRANSITIONS/STEP_TRANSITIONS as an
allowed-transition test, plus a representative sample of disallowed ones —
including every terminal state trying to move anywhere. No DB fixtures
needed: transition_instance/transition_step only touch the object passed
in, matching state_machine.py's "pure, side-effect-free" design.
"""

import pytest

from app.core.exceptions import AppError
from app.models.enums import InstanceStatus, StepStatus
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.services.workflows.state_machine import (
    INSTANCE_TRANSITIONS,
    STEP_TRANSITIONS,
    InvalidTransitionError,
    transition_instance,
    transition_step,
)

ALL_ALLOWED_INSTANCE_TRANSITIONS = [
    (current, target) for current, targets in INSTANCE_TRANSITIONS.items() for target in targets
]

ALL_ALLOWED_STEP_TRANSITIONS = [
    (current, target) for current, targets in STEP_TRANSITIONS.items() for target in targets
]

DISALLOWED_INSTANCE_TRANSITIONS = [
    # Every terminal state must reject every attempted transition, except
    # FAILED -> RUNNING (Phase 13b manual retry, see INSTANCE_TRANSITIONS) —
    # FAILED -> PENDING specifically is still disallowed either way.
    (InstanceStatus.COMPLETED, InstanceStatus.RUNNING),
    (InstanceStatus.FAILED, InstanceStatus.PENDING),
    (InstanceStatus.REJECTED, InstanceStatus.RUNNING),
    (InstanceStatus.CANCELLED, InstanceStatus.RUNNING),
    # Non-terminal states skipping steps they shouldn't be able to skip.
    (InstanceStatus.PENDING, InstanceStatus.COMPLETED),
    (InstanceStatus.PENDING, InstanceStatus.WAITING_APPROVAL),
    (InstanceStatus.WAITING_APPROVAL, InstanceStatus.WAITING_EXTERNAL),
    (InstanceStatus.WAITING_EXTERNAL, InstanceStatus.WAITING_APPROVAL),
    (InstanceStatus.WAITING_APPROVAL, InstanceStatus.COMPLETED),
]

DISALLOWED_STEP_TRANSITIONS = [
    (StepStatus.COMPLETED, StepStatus.RUNNING),
    # FAILED -> PENDING is Phase 13b's one deliberate exception (manual
    # retry) — see STEP_TRANSITIONS. FAILED -> RUNNING directly is still
    # disallowed either way: even a retry has to re-enter at PENDING like
    # every other step, not skip straight to RUNNING.
    (StepStatus.FAILED, StepStatus.RUNNING),
    (StepStatus.SKIPPED, StepStatus.RUNNING),
    (StepStatus.REJECTED, StepStatus.COMPLETED),
    (StepStatus.PENDING, StepStatus.COMPLETED),
    (StepStatus.WAITING_APPROVAL, StepStatus.RUNNING),
    (StepStatus.WAITING_EXTERNAL, StepStatus.RUNNING),
    (StepStatus.WAITING_EXTERNAL, StepStatus.FAILED),
]


@pytest.mark.parametrize("current,target", ALL_ALLOWED_INSTANCE_TRANSITIONS)
def test_every_allowed_instance_transition_succeeds(
    current: InstanceStatus, target: InstanceStatus
) -> None:
    instance = WorkflowInstance(status=current)
    transition_instance(instance, target)
    assert instance.status == target


@pytest.mark.parametrize("current,target", DISALLOWED_INSTANCE_TRANSITIONS)
def test_disallowed_instance_transitions_raise(
    current: InstanceStatus, target: InstanceStatus
) -> None:
    instance = WorkflowInstance(status=current)
    with pytest.raises(InvalidTransitionError):
        transition_instance(instance, target)
    assert instance.status == current, "status must not change on a rejected transition"


def test_invalid_transition_error_is_an_app_error() -> None:
    assert issubclass(InvalidTransitionError, AppError)
    assert InvalidTransitionError("pending", "completed").status_code == 409


@pytest.mark.parametrize("current,target", ALL_ALLOWED_STEP_TRANSITIONS)
def test_every_allowed_step_transition_succeeds(
    current: StepStatus, target: StepStatus
) -> None:
    step = WorkflowStepInstance(status=current)
    transition_step(step, target)
    assert step.status == target


@pytest.mark.parametrize("current,target", DISALLOWED_STEP_TRANSITIONS)
def test_disallowed_step_transitions_raise(current: StepStatus, target: StepStatus) -> None:
    step = WorkflowStepInstance(status=current)
    with pytest.raises(InvalidTransitionError):
        transition_step(step, target)
    assert step.status == current


def test_every_status_value_appears_in_its_transition_table() -> None:
    """Guards against a future new enum member silently having no row in
    the transition table (which would make transition_instance/_step raise
    a KeyError instead of the intended InvalidTransitionError)."""
    assert set(InstanceStatus) == set(INSTANCE_TRANSITIONS.keys())
    assert set(StepStatus) == set(STEP_TRANSITIONS.keys())
