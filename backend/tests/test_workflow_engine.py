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

Since Phase 9, `recommend_access` is a real ai_action step (see
services/ai/service.py), which means any test that resumes onboarding past
manager_approval needs a real Employee (recommend_access does a real
employee_repo lookup) and a mocked OpenAI client (no network calls, no API
key, no non-determinism in CI) — see `_new_hire_with_package` and
`_mock_recommendation` below. This file is about engine mechanics, not
about the AI service itself; test_ai_service.py covers that directly.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.employee import Employee
from app.models.enums import EmployeeStatus, EmploymentType, InstanceStatus, RiskLevel, StepStatus
from app.models.workflow import WorkflowInstance
from app.repositories import access_package_repo, department_repo, employee_repo
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import advance_workflow, resume_workflow_step, start_workflow
from app.workers.runner import poll_once


@pytest.fixture(autouse=True)
def _load_definitions(db_session: Session) -> None:
    load_all_definitions(db_session)


def _step(instance, key: str):
    return next(s for s in instance.step_instances if s.step_key == key)


def _new_hire_with_package(db: Session) -> tuple[Employee, str]:
    """A real Employee + a real AccessPackage, so recommend_access's real
    employee_repo/access_package_repo lookups have something to find.
    Returns the package's name so tests can mock a recommendation that
    actually matches a catalog row."""
    dept = department_repo.create(db, name=f"Dept-{uuid.uuid4()}")
    package_name = f"Engineering - Standard {uuid.uuid4()}"
    access_package_repo.create(
        db,
        name=package_name,
        department_id=dept.id,
        risk_level=RiskLevel.LOW,
        included_systems=["Slack", "GitHub"],
        description="Standard engineering access.",
    )
    employee = employee_repo.create(
        db,
        first_name="Jamie",
        last_name="Rivera",
        work_email=f"jamie-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 8, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    return employee, package_name


class _FakeRecommendation(BaseModel):
    recommended_package_name: str
    confidence_score: float
    explanation: str
    missing_information: list[str] = []


def _mock_recommendation(
    monkeypatch: pytest.MonkeyPatch, *, package_name: str, confidence: float
) -> None:
    """Patches services/ai/service.py's OpenAI client factory so
    recommend_access resolves deterministically — no network call, no API
    key, no cost, no flakiness from a real model's variance."""
    parsed = _FakeRecommendation(
        recommended_package_name=package_name,
        confidence_score=confidence,
        explanation="Mocked for engine test.",
    )
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=None))],
        usage=SimpleNamespace(total_tokens=42),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kwargs: fake_completion))
    )
    monkeypatch.setattr("app.services.ai.service._client", lambda: fake_client)


def test_onboarding_happy_path_completes_after_both_approvals(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package_name = _new_hire_with_package(db_session)
    # Low confidence — the default a real ambiguous recommendation might
    # get — so requires_human_review comes back True and it_review_access
    # pauses, exercising the second approval in this same test.
    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.4)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(employee.id)},
        dedup_key=f"test-onboarding-{uuid.uuid4()}",
        employee_id=employee.id,
    )

    # validate_employee ran and completed synchronously; manager_approval
    # is next and pauses the whole instance.
    assert instance.status == InstanceStatus.WAITING_APPROVAL
    assert _step(instance, "validate_employee").status == StepStatus.COMPLETED
    assert _step(instance, "manager_approval").status == StepStatus.WAITING_APPROVAL

    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # recommend_access ran for real (mocked OpenAI call) with low
    # confidence, so requires_human_review is True and it_review_access
    # pauses again.
    assert instance.status == InstanceStatus.WAITING_APPROVAL
    assert _step(instance, "recommend_access").status == StepStatus.COMPLETED
    assert _step(instance, "recommend_access").output_data["requires_human_review"] is True
    assert _step(instance, "recommend_access").output_data["recommended_package_name"] == (
        package_name
    )
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


def test_high_confidence_recommendation_skips_it_review_step(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package_name = _new_hire_with_package(db_session)
    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.95)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(employee.id)},
        dedup_key=f"test-skip-{uuid.uuid4()}",
        employee_id=employee.id,
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # No second approval pause this time — it_review_access's condition is
    # false, so the engine skips straight through to the mcp_tool steps.
    assert instance.status == InstanceStatus.COMPLETED
    assert _step(instance, "recommend_access").output_data["requires_human_review"] is False
    assert _step(instance, "it_review_access").status == StepStatus.SKIPPED


def test_mcp_tool_failure_retries_then_recovers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package_name = _new_hire_with_package(db_session)
    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.95)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(employee.id),
            "force_failure_steps": ["create_it_tasks"],
        },
        dedup_key=f"test-retry-{uuid.uuid4()}",
        employee_id=employee.id,
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
    assert failing_step.scheduled_at > datetime.now(UTC)
    assert "Simulated failure" in failing_step.error_message

    # Simulate both "the retry is now due" and "the transient failure is
    # gone" without sleeping out the real backoff in the test suite.
    instance.input_data = {**instance.input_data, "force_failure_steps": []}
    failing_step.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(instance)
    db_session.add(failing_step)
    db_session.commit()

    instance = advance_workflow(db_session, instance)

    assert instance.status == InstanceStatus.COMPLETED
    failing_step = _step(instance, "create_it_tasks")
    assert failing_step.status == StepStatus.COMPLETED
    assert failing_step.attempt_count == 2


def test_mcp_tool_retries_exhausted_fails_the_workflow(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package_name = _new_hire_with_package(db_session)
    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.95)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(employee.id),
            "force_failure_steps": ["create_it_tasks"],
        },
        dedup_key=f"test-exhausted-{uuid.uuid4()}",
        employee_id=employee.id,
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )

    # Drive it through both remaining allowed attempts (max_attempts=3;
    # the first attempt already happened above) without waiting on backoff.
    for _ in range(2):
        step = _step(instance, "create_it_tasks")
        step.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.add(step)
        db_session.commit()
        instance = advance_workflow(db_session, instance)

    assert instance.status == InstanceStatus.FAILED
    failed_step = _step(instance, "create_it_tasks")
    assert failed_step.status == StepStatus.FAILED
    assert failed_step.attempt_count == 3


def test_mcp_tool_continue_failure_behavior_does_not_fail_the_workflow(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package_name = _new_hire_with_package(db_session)
    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.95)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(employee.id),
            "force_failure_steps": ["notify_slack"],
        },
        dedup_key=f"test-continue-{uuid.uuid4()}",
        employee_id=employee.id,
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


def test_worker_poll_advances_a_due_retry(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package_name = _new_hire_with_package(db_session)
    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.95)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={
            "employee_id": str(employee.id),
            "force_failure_steps": ["create_it_tasks"],
        },
        dedup_key=f"test-worker-{uuid.uuid4()}",
        employee_id=employee.id,
    )
    instance = resume_workflow_step(
        db_session, instance, _step(instance, "manager_approval"), decision="approved"
    )
    assert instance.status == InstanceStatus.WAITING_EXTERNAL

    instance.input_data = {**instance.input_data, "force_failure_steps": []}
    step = _step(instance, "create_it_tasks")
    step.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
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
