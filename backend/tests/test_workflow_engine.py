"""Integration tests for the workflow execution engine: start, advance,
pause for approval, resume, retry-and-recover, retries-exhausted, and
idempotency. Runs against the two real workflows/*.json templates via
load_all_definitions — not fixtures standing in for them — so a change to
either JSON file that breaks an assumption the engine makes shows up here,
not just at `docker compose up`.

`resume_workflow_step` is called directly to simulate a human decision,
standing in for the real ApprovalRequest/ApprovalDecision flow Phase 7
adds — this proves pause/resume is correct before Phase 7 exists to
exercise it for real.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import InstanceStatus, StepStatus
from app.models.workflow import WorkflowInstance
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import advance_workflow, resume_workflow_step, start_workflow
from app.workers.runner import poll_once


@pytest.fixture(autouse=True)
def _load_definitions(db_session: Session) -> None:
    load_all_definitions(db_session)


def _step(instance, key: str):
    return next(s for s in instance.step_instances if s.step_key == key)


def test_onboarding_happy_path_completes_after_both_approvals(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(uuid.uuid4())},
        dedup_key=f"test-onboarding-{uuid.uuid4()}",
    )

    # validate_employee ran and completed synchronously; manager_approval
    # is next and pauses the whole instance.
    assert instance.status == InstanceStatus.WAITING_APPROVAL
    assert _step(instance, "validate_employee").status == StepStatus.COMPLETED
    assert _step(instance, "manager_approval").status == StepStatus.WAITING_APPROVAL

    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # recommend_access (ai stub) ran and defaulted requires_human_review to
    # True, so it_review_access's condition is true and pauses again.
    assert instance.status == InstanceStatus.WAITING_APPROVAL
    assert _step(instance, "recommend_access").status == StepStatus.COMPLETED
    assert _step(instance, "recommend_access").output_data["requires_human_review"] is True
    assert _step(instance, "it_review_access").status == StepStatus.WAITING_APPROVAL

    instance = resume_workflow_step(
        db_session, instance, _step(instance, "it_review_access"), decision="approved"
    )

    assert instance.status == InstanceStatus.COMPLETED
    assert instance.completed_at is not None
    for key in ("create_it_tasks", "schedule_orientation", "notify_slack"):
        step = _step(instance, key)
        assert step.status == StepStatus.COMPLETED
        assert step.output_data["stub"] is True


def test_manager_rejection_stops_the_workflow(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(uuid.uuid4())},
        dedup_key=f"test-rejection-{uuid.uuid4()}",
    )
    instance = resume_workflow_step(
        db_session,
        instance,
        _step(instance, "manager_approval"),
        decision="rejected",
        notes="Not approved this quarter.",
    )

    assert instance.status == InstanceStatus.REJECTED
    assert instance.completed_at is not None
    assert _step(instance, "manager_approval").status == StepStatus.REJECTED
    # Nothing downstream of the rejected step should ever have run.
    assert _step(instance, "recommend_access").status == StepStatus.PENDING


def test_ai_requires_review_false_skips_it_review_step(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(uuid.uuid4()), "ai_requires_review": False},
        dedup_key=f"test-skip-{uuid.uuid4()}",
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # No second approval pause this time — it_review_access's condition is
    # false, so the engine skips straight through to the mcp_tool steps.
    assert instance.status == InstanceStatus.COMPLETED
    assert _step(instance, "it_review_access").status == StepStatus.SKIPPED


def test_mcp_tool_failure_retries_then_recovers(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(uuid.uuid4()),
            "ai_requires_review": False,
            "force_failure_steps": ["create_it_tasks"],
        },
        dedup_key=f"test-retry-{uuid.uuid4()}",
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # create_it_tasks failed once; failure_behavior=retry with max_attempts=3
    # parks the instance in waiting_external instead of failing outright.
    assert instance.status == InstanceStatus.WAITING_EXTERNAL
    failing_step = _step(instance, "create_it_tasks")
    assert failing_step.status == StepStatus.PENDING
    assert failing_step.attempt_count == 1
    assert failing_step.scheduled_at is not None
    assert failing_step.scheduled_at > datetime.now(timezone.utc)
    assert "Simulated failure" in failing_step.error_message

    # Simulate both "the retry is now due" and "the transient failure is
    # gone" without sleeping out the real backoff in the test suite.
    instance.input_data = {**instance.input_data, "force_failure_steps": []}
    failing_step.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.add(instance)
    db_session.add(failing_step)
    db_session.commit()

    instance = advance_workflow(db_session, instance)

    assert instance.status == InstanceStatus.COMPLETED
    failing_step = _step(instance, "create_it_tasks")
    assert failing_step.status == StepStatus.COMPLETED
    assert failing_step.attempt_count == 2


def test_mcp_tool_retries_exhausted_fails_the_workflow(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(uuid.uuid4()),
            "ai_requires_review": False,
            "force_failure_steps": ["create_it_tasks"],
        },
        dedup_key=f"test-exhausted-{uuid.uuid4()}",
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # Drive it through both remaining allowed attempts (max_attempts=3;
    # the first attempt already happened above) without waiting on backoff.
    for _ in range(2):
        step = _step(instance, "create_it_tasks")
        step.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.add(step)
        db_session.commit()
        instance = advance_workflow(db_session, instance)

    assert instance.status == InstanceStatus.FAILED
    failed_step = _step(instance, "create_it_tasks")
    assert failed_step.status == StepStatus.FAILED
    assert failed_step.attempt_count == 3


def test_mcp_tool_continue_failure_behavior_does_not_fail_the_workflow(
    db_session: Session,
) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(uuid.uuid4()),
            "ai_requires_review": False,
            "force_failure_steps": ["notify_slack"],
        },
        dedup_key=f"test-continue-{uuid.uuid4()}",
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # notify_slack's failure_behavior is "continue" — it fails permanently
    # (no retry configured for it), but the workflow still completes rather
    # than failing over a non-critical notification.
    assert instance.status == InstanceStatus.COMPLETED
    assert _step(instance, "notify_slack").status == StepStatus.FAILED


def test_validation_failure_fails_the_workflow_immediately(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={},  # missing required employee_id
        dedup_key=f"test-validation-{uuid.uuid4()}",
    )
    assert instance.status == InstanceStatus.FAILED
    step = _step(instance, "validate_employee")
    assert step.status == StepStatus.FAILED
    assert "employee_id" in step.error_message


def test_start_workflow_is_idempotent_on_dedup_key(db_session: Session) -> None:
    dedup_key = f"test-idempotent-{uuid.uuid4()}"
    first = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(uuid.uuid4())},
        dedup_key=dedup_key,
    )
    second = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(uuid.uuid4())},
        dedup_key=dedup_key,
    )
    assert first.id == second.id


def test_start_workflow_raises_not_found_for_unknown_key(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        start_workflow(
            db_session,
            workflow_key="does_not_exist",
            input_data={},
            dedup_key=f"test-unknown-{uuid.uuid4()}",
        )


def test_resume_workflow_step_rejects_a_step_not_waiting_for_approval(
    db_session: Session,
) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(uuid.uuid4())},
        dedup_key=f"test-conflict-{uuid.uuid4()}",
    )
    already_completed_step = _step(instance, "validate_employee")
    with pytest.raises(ConflictError):
        resume_workflow_step(db_session, instance, already_completed_step, decision="approved")


def test_worker_poll_advances_a_due_retry(db_session: Session) -> None:
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(uuid.uuid4()),
            "ai_requires_review": False,
            "force_failure_steps": ["create_it_tasks"],
        },
        dedup_key=f"test-worker-{uuid.uuid4()}",
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )
    assert instance.status == InstanceStatus.WAITING_EXTERNAL

    instance.input_data = {**instance.input_data, "force_failure_steps": []}
    step = _step(instance, "create_it_tasks")
    step.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.add(instance)
    db_session.add(step)
    db_session.commit()

    # poll_once() opens its own DB session (same process, matching how the
    # real worker runs) — a separate, committed transaction is what proves
    # this isn't relying on db_session's in-memory state to pass.
    processed = poll_once()
    assert processed == 1

    db_session.expire_all()
    refreshed = db_session.get(WorkflowInstance, instance.id)
    assert refreshed is not None
    assert refreshed.status == InstanceStatus.COMPLETED
