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
from app.models.inbound_event import InboundEvent
from app.models.integration import HealthCheckResult, IntegrationConnection
from app.models.mcp_tool_execution import MCPToolExecution
from app.models.notification import Notification
from app.models.organization import ExternalIdentity, Organization
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


_DEFAULT_MCP_TOOL_RESULTS: dict[str, dict[str, object]] = {
    "create_jira_task": {
        "issue_key": "MOCK-1001",
        "issue_url": "https://mock-jira.example.com/browse/MOCK-1001",
        "status": "created",
    },
    "send_slack_notification": {
        "message_ts": "1700000000.000001",
        "channel": "#mock",
        "status": "sent",
    },
    "schedule_calendar_event": {
        "event_id": "mock-event-id",
        "event_url": "https://calendar.google.com/calendar/event?eid=mock-event-id",
        "status": "scheduled",
    },
    # Only actually exercised by tests whose fake OpenAI client returns a
    # tool_calls response (see the default _mock_openai_by_default fixture
    # below, which never does) — present here so any test that does isn't
    # the first to discover this dict needs a fourth entry.
    "lookup_employee": {
        "found": True,
        "employee_id": "00000000-0000-0000-0000-000000000000",
        "first_name": "Mock",
        "last_name": "Employee",
        "work_email": "mock.employee@cordant.io",
        "job_title": "Software Engineer",
        "department_name": "Engineering",
        "employment_type": "full_time",
        "status": "active",
        "risk_level": "low",
    },
}


@pytest.fixture(autouse=True)
def _mock_mcp_client_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets a mocked MCP client by default, for exactly the
    reason the OpenAI autouse fixture above exists: once execute_mcp_tool
    is real (Phase 10), any test that walks a happy path through an
    mcp_tool step would otherwise make a real network call to mcp_server
    during `pytest` — the same class of bug the OpenAI incident was, just
    applied to a second integration. Building the fixture in from the
    start here rather than discovering it after a confusing failure.

    Patches services/integrations/mcp_client._call_tool_async specifically
    (not the whole call_tool function) — call_tool's own logic (writing
    the MCPToolExecution audit row, timing, error translation) still runs
    for real in every test; only the actual network call is faked. Tests
    that care about MCP failure handling override this themselves via
    monkeypatch, the same pattern test_ai_service.py already uses for
    OpenAI.
    """

    async def fake_call_tool_async(
        server_url: str, tool_name: str, arguments: dict[str, object], timeout_seconds: float
    ) -> dict[str, object]:
        if tool_name not in _DEFAULT_MCP_TOOL_RESULTS:
            raise ValueError(f"no default mock result configured for MCP tool {tool_name!r}")
        return dict(_DEFAULT_MCP_TOOL_RESULTS[tool_name])

    monkeypatch.setattr(
        "app.services.integrations.mcp_client._call_tool_async", fake_call_tool_async
    )


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

    tool_calls=None here means recommend_access_package's agentic loop
    (see services/ai/service.py) exits after its first round for any test
    using this default — it never actually calls lookup_employee unless a
    test opts into simulating that explicitly, same as test_ai_service.py
    already does per-test for OpenAI generally.
    """
    fake_completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    parsed=_DefaultAIResponse(), refusal=None, tool_calls=None, content=None
                )
            )
        ],
        usage=SimpleNamespace(total_tokens=0),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kwargs: fake_completion))
    )
    monkeypatch.setattr("app.services.ai.service._client", lambda: fake_client)


@pytest.fixture(scope="session", autouse=True)
def _refuse_to_run_against_a_seeded_database() -> None:
    """Root-caused during the Phase 3 handover: the suite was flaky
    depending on who ran it. Not a test-ordering bug — the two runs were
    against two different databases. This project's own documented local
    setup (README "Running the backend without Docker") has you point
    DATABASE_URL at the same Postgres `docker compose up` exposes on
    5433, *after* running `python -m app.db.seed` against it (app/db/seed.py
    runs on every backend container start). Following those instructions
    to the letter, then running `pytest` from the same shell, points the
    suite at a database that already has Marcus Webb, Human Resources, and
    five other departments in it. A freshly migrated empty database — what
    this project's own sandbox always used — never has that problem. Same
    code, same tests, two different answers, and the difference is
    invisible from the pytest output.

    This is the AUTH_MODE startup-guard pattern (app/core/auth_mode.py)
    applied to the test suite: the failure mode has no useful runtime
    symptom until some test's row count or name assertion happens to
    collide with seed data, so refusing loudly and immediately, before a
    single test runs, is the only signal that cannot be missed or
    misdiagnosed as flakiness.

    Checks for the seed's "Human Resources" department specifically —
    cheap, and it exists if and only if app/db/seed.py has ever run
    against this database.
    """
    session = SessionLocal()
    try:
        seeded = (
            session.query(Department).filter(Department.name == "Human Resources").first()
        )
    finally:
        session.close()
    if seeded is not None:
        pytest.exit(
            "DATABASE_URL points at a database that already contains seed "
            "data (found the demo 'Human Resources' department, created by "
            "app/db/seed.py). This is almost certainly the same Postgres "
            "`docker compose up` seeds on every backend container start — "
            "running the suite against it produces results that depend on "
            "what else has touched that database, not on the code under "
            "test.\n\n"
            "Point DATABASE_URL at a dedicated database that has migrations "
            "applied and has never run app/db/seed.py, for example:\n"
            "  createdb meridian_flow_test\n"
            '  $env:DATABASE_URL = "postgresql+psycopg://meridian:meridian@localhost:5433/meridian_flow_test"\n'
            "  alembic upgrade head\n"
            "  pytest",
            returncode=1,
        )


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
    delete order by hand. ApprovalDecision, ApprovalRequest, AIExecution,
    and MCPToolExecution (all FK to workflow/step instances, and in
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
            session.execute(delete(MCPToolExecution))
            session.execute(delete(Notification))
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
            # V2 Module 1. Results before connections — HealthCheckResult
            # has a real FK to integration_connections.id, and this file's
            # own history is the argument for getting that order right the
            # first time: one wrong delete order previously aborted the
            # cleanup transaction and left every table's rows behind for
            # the remainder of the run.
            session.execute(delete(HealthCheckResult))
            # Inbound events reference workflow_instances and themselves
            # (duplicate_of_id), and external identities reference
            # integration_connections — both must go before the tables they
            # point at, for the same reason spelled out above.
            session.execute(delete(InboundEvent))
            session.execute(delete(ExternalIdentity))
            session.execute(delete(Organization))
            session.execute(delete(IntegrationConnection))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
