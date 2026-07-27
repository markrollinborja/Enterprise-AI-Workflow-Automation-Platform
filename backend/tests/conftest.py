from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.access_package import AccessPackage
from app.models.ai_execution import AIExecution
from app.models.application import Application
from app.models.approval import ApprovalDecision, ApprovalRequest
from app.models.department import Department
from app.models.employee import Employee
from app.models.user import User
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowStepInstance,
)


class _DefaultAIResponse(BaseModel):
    """A superset of both real structured-output shapes services/ai/service.py
    asks OpenAI for (AccessPackageRecommendationOutput and
    JustificationSummaryOutput) — whichever task a given test's workflow
    happens to reach, the fields that task's code actually touches are
    present here. A real Pydantic model (not a bare SimpleNamespace) because
    _recommend_access_package calls .model_dump() on it."""

    recommended_package_name: str = "Default Mocked Package"
    confidence_score: float = 0.3
    explanation: str = "Default autouse mock — see conftest.py."
    missing_information: list[str] = []
    summary: str = "Default autouse mock — see conftest.py."


@pytest.fixture(autouse=True)
def _mock_openai_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets a mocked OpenAI client by default, regardless of
    whether a real OPENAI_API_KEY happens to be set in .env — no test's
    pass/fail should depend on environment state, cost real money, or hit
    the network. Confidence is deliberately below _CONFIDENCE_THRESHOLD so
    requires_human_review comes back True on recommend_access whenever a
    step has requires_review enabled: approval/engine tests that reach that
    step without caring about AI content still see the it_review_access
    pause they were written against, matching the old stub's behavior.

    Tests that care about AI behavior specifically (confidence thresholds,
    the catalog constraint, failure paths — see test_ai_service.py,
    test_workflow_engine.py) call
    monkeypatch.setattr("app.services.ai.service._client", ...) themselves,
    which simply overrides this patch for that one test.
    """
    fake_completion = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(parsed=_DefaultAIResponse(), refusal=None))
        ],
        usage=SimpleNamespace(total_tokens=0),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kwargs: fake_completion))
    )
    monkeypatch.setattr("app.services.ai.service._client", lambda: fake_client)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session():
    """Yields a real session against the test database (see DATABASE_URL in
    CI / your local .env). Cleans up test-created rows after each test —
    simple and correct for a handful of tables; Phase 14 can move to
    transaction-rollback isolation once there are many more.

    Deletion order matters here: users.employee_id and Employee's own
    self-referential manager_id both need clearing before the rows they
    point at can be deleted, or Postgres rejects the delete on an FK
    violation — nulling both out first sidesteps having to compute a safe
    delete order by hand. ApprovalDecision, ApprovalRequest, and
    AIExecution (all FK to workflow/step instances, and in
    ApprovalDecision/AIExecution's case to users too) go first, then
    WorkflowEvent, then step/instance rows, before employees/users
    themselves. AccessPackage has a real FK to Department
    (department_id) and must be deleted before Department — this was
    previously wrong (Department was deleted first), which threw a
    ForeignKeyViolation, aborted the transaction before commit(), and left
    every table's rows from that test un-deleted for the rest of the run.
    workflow_definitions and applications genuinely have no incoming FK at
    this point (WorkflowInstance.input_data only references an
    application_id/access_package_id inside its own JSON blob, never a
    real foreign key) so they can go last, in any order. The whole block
    is wrapped in try/rollback/close so a future ordering mistake fails
    that one test cleanly instead of silently corrupting every test after
    it, the way this one did.
    """
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        try:
            session.execute(delete(ApprovalDecision))
            session.execute(delete(ApprovalRequest))
            session.execute(delete(AIExecution))
            session.execute(delete(WorkflowEvent))
            session.execute(delete(WorkflowStepInstance))
            session.execute(delete(WorkflowInstance))
            session.execute(update(User).values(employee_id=None))
            session.execute(delete(User))
            session.execute(update(Employee).values(manager_id=None))
            session.execute(delete(Employee))
            session.execute(delete(AccessPackage))
            session.execute(delete(Department))
            session.execute(delete(WorkflowDefinition))
            session.execute(delete(Application))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
