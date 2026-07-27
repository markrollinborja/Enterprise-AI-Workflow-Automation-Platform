"""Unit/integration tests for services/ai/service.py — the real AI service
that replaced execute_ai_action_stub in Phase 9. No real OpenAI calls
anywhere in this file: `_client` is monkeypatched to return a fake
response object, matching how test_workflow_engine.py mocks it for engine
tests. This file is the AI service's own coverage — confidence routing,
graceful fallback, the dynamic catalog constraint, and the AIExecution
audit trail — independent of engine mechanics.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.access_package import AccessPackage
from app.models.ai_execution import AIExecution
from app.models.employee import Employee
from app.models.enums import AIExecutionStatus, EmployeeStatus, EmploymentType, RiskLevel
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.repositories import access_package_repo, department_repo, employee_repo
from app.services.ai import service as ai_service
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import start_workflow


@pytest.fixture(autouse=True)
def _load_definitions(db_session: Session) -> None:
    load_all_definitions(db_session)


@pytest.fixture(autouse=True)
def _fake_api_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A non-empty key by default so the "not configured" short-circuit
    only fires in the tests that explicitly want it. Never a real key —
    the client itself is mocked in every test that reaches it."""
    get_settings.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    yield
    get_settings.cache_clear()


class _FakeRecommendation(BaseModel):
    recommended_package_name: str
    confidence_score: float
    explanation: str
    missing_information: list[str] = []


class _FakeSummary(BaseModel):
    summary: str
    confidence_score: float
    explanation: str


def _mock_client(
    monkeypatch: pytest.MonkeyPatch, parsed: BaseModel | None, refusal: str | None = None
) -> None:
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=refusal))],
        usage=SimpleNamespace(total_tokens=99),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kwargs: fake_completion))
    )
    monkeypatch.setattr("app.services.ai.service._client", lambda: fake_client)


def _new_hire(db: Session) -> tuple[Employee, AccessPackage]:
    dept = department_repo.create(db, name=f"Dept-{uuid.uuid4()}")
    package = access_package_repo.create(
        db,
        name=f"Engineering - Standard {uuid.uuid4()}",
        department_id=dept.id,
        risk_level=RiskLevel.LOW,
        included_systems=["GitHub", "Slack"],
        description="Standard engineering access.",
    )
    employee = employee_repo.create(
        db,
        first_name="Sam",
        last_name="Okafor",
        work_email=f"sam-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 8, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    return employee, package


def _onboarding_recommend_access_step(
    db: Session, employee_id: uuid.UUID
) -> tuple[WorkflowInstance, WorkflowStepInstance]:
    """Starts a real onboarding instance and returns its (still-pending)
    recommend_access step + the instance — manager_approval pauses the
    engine before recommend_access ever runs, so this step is untouched
    and safe to drive directly."""
    instance = start_workflow(
        db,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(employee_id)},
        dedup_key=f"test-ai-{uuid.uuid4()}",
        employee_id=employee_id,
    )
    step_row = next(s for s in instance.step_instances if s.step_key == "recommend_access")
    return instance, step_row


def _access_request_summarize_step(
    db: Session,
) -> tuple[WorkflowInstance, WorkflowStepInstance]:
    """Same idea for software_access_request's summarize_justification —
    manager_approval (medium/high risk, so not auto-approved) pauses the
    engine first."""
    instance = start_workflow(
        db,
        workflow_key="software_access_request",
        input_data={
            "employee_id": str(uuid.uuid4()),
            "application_id": str(uuid.uuid4()),
            "justification": "Need elevated access to debug a production incident.",
            "application_risk_level": "medium",
            "auto_approved": False,
        },
        dedup_key=f"test-ai-summarize-{uuid.uuid4()}",
    )
    step_row = next(
        s for s in instance.step_instances if s.step_key == "summarize_justification"
    )
    return instance, step_row


def _ai_executions_for(db: Session, step_instance_id: uuid.UUID) -> list[AIExecution]:
    return list(
        db.scalars(select(AIExecution).where(AIExecution.step_instance_id == step_instance_id))
    )


def test_recommend_access_package_high_confidence_does_not_require_review(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package = _new_hire(db_session)
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)
    _mock_client(
        monkeypatch,
        _FakeRecommendation(
            recommended_package_name=package.name,
            confidence_score=0.92,
            explanation="Clear fit.",
        ),
    )

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="recommend_access_package",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=True,
    )

    assert result.status == "completed"
    assert result.output_data is not None
    assert result.output_data["requires_human_review"] is False
    assert result.output_data["recommended_package_id"] == str(package.id)

    executions = _ai_executions_for(db_session, step_row.id)
    assert len(executions) == 1
    assert executions[0].status == AIExecutionStatus.COMPLETED
    assert executions[0].confidence_score == pytest.approx(0.92)
    assert executions[0].tokens_used == 99


def test_recommend_access_package_low_confidence_requires_review(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, package = _new_hire(db_session)
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)
    _mock_client(
        monkeypatch,
        _FakeRecommendation(
            recommended_package_name=package.name,
            confidence_score=0.3,
            explanation="Ambiguous title.",
        ),
    )

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="recommend_access_package",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=True,
    )

    assert result.output_data is not None
    assert result.output_data["requires_human_review"] is True


def test_recommend_access_package_review_disabled_never_requires_review(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a low-confidence result doesn't gate anything when
    requires_review_enabled is False — the step's own JSON config decides
    whether this task's confidence is ever consulted at all."""
    employee, package = _new_hire(db_session)
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)
    _mock_client(
        monkeypatch,
        _FakeRecommendation(
            recommended_package_name=package.name, confidence_score=0.1, explanation="Low."
        ),
    )

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="recommend_access_package",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=False,
    )

    assert result.output_data is not None
    assert result.output_data["requires_human_review"] is False


def test_recommend_access_package_missing_api_key_fails_gracefully(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    employee, _package = _new_hire(db_session)
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="recommend_access_package",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=True,
    )

    assert result.status == "failed"
    # Safe-default fallback: a step that couldn't run must never let a
    # downstream review gate silently skip.
    assert result.output_data == {"requires_human_review": True}
    executions = _ai_executions_for(db_session, step_row.id)
    assert executions[0].status == AIExecutionStatus.FAILED
    get_settings.cache_clear()


def test_recommend_access_package_no_catalog_fails_gracefully(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dept = department_repo.create(db_session, name=f"Dept-{uuid.uuid4()}")
    employee = employee_repo.create(
        db_session,
        first_name="No",
        last_name="Catalog",
        work_email=f"nocatalog-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 8, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="recommend_access_package",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=True,
    )

    assert result.status == "failed"
    assert result.output_data == {"requires_human_review": True}


def test_recommend_access_package_refusal_fails_gracefully(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, _package = _new_hire(db_session)
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)
    _mock_client(monkeypatch, parsed=None, refusal="I can't help with that.")

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="recommend_access_package",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=True,
    )

    assert result.status == "failed"
    assert result.error_message == "I can't help with that."


def test_summarize_justification_success(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, step_row = _access_request_summarize_step(db_session)
    _mock_client(
        monkeypatch,
        _FakeSummary(
            summary="Requesting temporary elevated access to resolve an incident.",
            confidence_score=0.8,
            explanation="Clear, specific justification.",
        ),
    )

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="summarize_justification",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=False,
    )

    assert result.status == "completed"
    assert result.output_data is not None
    # This task never gates review, regardless of confidence.
    assert result.output_data["requires_human_review"] is False
    executions = _ai_executions_for(db_session, step_row.id)
    assert executions[0].status == AIExecutionStatus.COMPLETED


def test_summarize_justification_missing_api_key_fails_without_fallback_output(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    instance, step_row = _access_request_summarize_step(db_session)

    result = ai_service.execute_ai_task(
        db_session,
        ai_task="summarize_justification",
        step_row=step_row,
        instance=instance,
        context={"input": instance.input_data},
        requires_review_enabled=False,
    )

    assert result.status == "failed"
    # Nothing downstream reads this step's output via a condition, so no
    # fallback output is needed (contrast with recommend_access_package).
    assert result.output_data is None
    get_settings.cache_clear()


def test_execute_ai_task_rejects_unknown_task(db_session: Session) -> None:
    employee, _package = _new_hire(db_session)
    instance, step_row = _onboarding_recommend_access_step(db_session, employee.id)

    with pytest.raises(ValueError, match="unknown ai_task"):
        ai_service.execute_ai_task(
            db_session,
            ai_task="not_a_real_task",
            step_row=step_row,
            instance=instance,
            context={"input": instance.input_data},
            requires_review_enabled=True,
        )


def test_recommendation_schema_structurally_rejects_names_outside_the_catalog() -> None:
    """The dynamic Literal constraint (see _build_recommendation_model) is
    a real schema restriction, not just a prompt instruction — proven here
    without any network call: constructing the dynamically-built model
    with a name outside its catalog must raise, exactly like any other
    invalid Pydantic field value."""
    model = ai_service._build_recommendation_model(["Engineering - Standard", "IT - Elevated"])
    model(
        recommended_package_name="Engineering - Standard",
        confidence_score=0.9,
        explanation="Fine.",
    )
    with pytest.raises(ValidationError):
        model(
            recommended_package_name="Something Not In The Catalog",
            confidence_score=0.9,
            explanation="Should never validate.",
        )
