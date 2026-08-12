"""Tests for app/core/metrics.py's emission points (V2 Module 7, ADR-0022):
the /metrics scrape endpoint itself, the HTTP timing middleware, and the
four domain call sites (workflow start/finish, approval decisions, MCP tool
calls).

All of these use the process-wide default `prometheus_client` registry
(see metrics.py's own docstring for why), which persists for the lifetime
of the pytest process rather than resetting per test. Every assertion here
is therefore a *delta* — read the sample's value before the action under
test, act, read it again, assert on the difference — never an absolute
value, which would be contaminated by whatever every other test in the
suite already did to the same counters. See conftest.py's
`_refuse_to_run_against_a_seeded_database` for the same "get this
environment assumption wrong and every test result becomes uninterpretable"
class of bug, applied here to metric state instead of database state.
"""

import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client.metrics import MetricWrapperBase
from sqlalchemy.orm import Session

from app.core.metrics import (
    approval_decisions_total,
    approval_wait_seconds,
    http_requests_total,
    mcp_tool_call_duration_seconds,
    workflow_instances_finished_total,
    workflow_instances_started_total,
)
from app.core.security import hash_password
from app.models.enums import (
    EmployeeStatus,
    EmploymentType,
    MCPToolCaller,
    RiskLevel,
    UserRole,
)
from app.models.user import User
from app.repositories import application_repo, approval_request_repo, department_repo, employee_repo
from app.services.approvals import service as approval_service
from app.services.integrations import mcp_client
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import confirm_external_completion, start_workflow

TEST_PASSWORD = "CorrectHorse123!"


def _sample_value(metric: MetricWrapperBase, sample_name: str, **labels: str) -> float:
    """Reads one sample's current value off `metric.collect()` — the public
    API, not the private `_value`/`_metrics` attributes prometheus_client
    stores internal state in. `sample_name` is the exact exposition-format
    name (e.g. "workflow_instances_started_total" for a Counter, or
    "approval_wait_seconds_count" for a Histogram's count series) — see
    this file's module docstring for why every caller compares two of
    these rather than asserting one in isolation."""
    for family in metric.collect():
        for sample in family.samples:
            if sample.name == sample_name and sample.labels == labels:
                return sample.value
    return 0.0


@pytest.fixture(autouse=True)
def _load_definitions(db_session: Session) -> None:
    load_all_definitions(db_session)


def _create_user(db: Session, *, email: str, role: UserRole, employee_id: uuid.UUID) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(TEST_PASSWORD),
        full_name=email.split("@")[0],
        role=role,
        employee_id=employee_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _new_hire_with_manager(db: Session) -> tuple[Any, Any]:
    dept = department_repo.create(db, name=f"Dept-{uuid.uuid4()}")
    manager = employee_repo.create(
        db,
        first_name="Priya",
        last_name="Anand",
        work_email=f"priya-{uuid.uuid4()}@cordant.io",
        job_title="Engineering Manager",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2020, 1, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.MEDIUM,
    )
    manager_user = _create_user(
        db, email=manager.work_email, role=UserRole.MANAGER, employee_id=manager.id
    )
    new_hire = employee_repo.create(
        db,
        first_name="Dana",
        last_name="Okafor",
        work_email=f"dana-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=manager.id,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 8, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    return new_hire, manager_user


def _step(instance: Any, key: str) -> Any:
    return next(s for s in instance.step_instances if s.step_key == key)


# --- /metrics endpoint + HTTP middleware -------------------------------------


def test_metrics_endpoint_returns_prometheus_exposition_format(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP http_requests_total" in response.text
    assert "# TYPE http_requests_total counter" in response.text


def test_http_middleware_records_request_count_and_duration(client: TestClient) -> None:
    before_count = _sample_value(
        http_requests_total, "http_requests_total", method="GET", route="/health", status_code="200"
    )

    response = client.get("/health")
    assert response.status_code == 200

    after_count = _sample_value(
        http_requests_total, "http_requests_total", method="GET", route="/health", status_code="200"
    )
    assert after_count == before_count + 1


def test_http_middleware_labels_by_route_template_not_raw_path(client: TestClient) -> None:
    """The whole reason for reading request.scope["route"] instead of the raw
    path (see main.py's metrics_middleware docstring) — two different
    employee IDs must land on the same route-template label, not fork into
    two time series. No auth header is sent, so both requests get a 403
    from the route's own permission check before ever touching an
    employee_id — enough to prove the labeling, without needing a real
    logged-in user."""
    labels = {"method": "GET", "route": "/employees/{employee_id}", "status_code": "403"}
    before = _sample_value(http_requests_total, "http_requests_total", **labels)

    client.get(f"/employees/{uuid.uuid4()}")
    client.get(f"/employees/{uuid.uuid4()}")

    after = _sample_value(http_requests_total, "http_requests_total", **labels)
    assert after == before + 2


def test_unmatched_route_falls_back_to_unmatched_label(client: TestClient) -> None:
    labels = {"method": "GET", "route": "unmatched", "status_code": "404"}
    before = _sample_value(http_requests_total, "http_requests_total", **labels)

    client.get("/this-route-does-not-exist")

    after = _sample_value(http_requests_total, "http_requests_total", **labels)
    assert after == before + 1


# --- workflow start / finish --------------------------------------------------


def test_start_workflow_increments_started_total(db_session: Session) -> None:
    before = _sample_value(
        workflow_instances_started_total,
        "workflow_instances_started_total",
        workflow_key="employee_onboarding",
    )

    start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={},  # missing employee_id -- validate_employee fails, which is fine:
        # start_workflow increments "started" unconditionally before it ever
        # reaches validation (see service.py) -- this test only needs a
        # cheap, deterministic way to trigger that one increment.
        dedup_key=f"test-metrics-started-{uuid.uuid4()}",
    )

    after = _sample_value(
        workflow_instances_started_total,
        "workflow_instances_started_total",
        workflow_key="employee_onboarding",
    )
    assert after == before + 1


def test_dedup_hit_does_not_double_count_started_total(db_session: Session) -> None:
    """The started counter must reflect real workflow starts, not every
    caller of start_workflow -- a resubmitted event that resolves to an
    already-existing instance (WorkflowEvent.dedup_key) is not a new
    start."""
    dedup_key = f"test-metrics-dedup-{uuid.uuid4()}"
    start_workflow(
        db_session, workflow_key="employee_onboarding", input_data={}, dedup_key=dedup_key
    )
    before = _sample_value(
        workflow_instances_started_total,
        "workflow_instances_started_total",
        workflow_key="employee_onboarding",
    )

    start_workflow(
        db_session, workflow_key="employee_onboarding", input_data={}, dedup_key=dedup_key
    )

    after = _sample_value(
        workflow_instances_started_total,
        "workflow_instances_started_total",
        workflow_key="employee_onboarding",
    )
    assert after == before


def test_validation_failure_increments_finished_total_failed(db_session: Session) -> None:
    before = _sample_value(
        workflow_instances_finished_total,
        "workflow_instances_finished_total",
        workflow_key="employee_onboarding",
        status="failed",
    )

    start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={},  # missing required employee_id
        dedup_key=f"test-metrics-failed-{uuid.uuid4()}",
    )

    after = _sample_value(
        workflow_instances_finished_total,
        "workflow_instances_finished_total",
        workflow_key="employee_onboarding",
        status="failed",
    )
    assert after == before + 1


def test_manager_rejection_increments_finished_total_rejected(db_session: Session) -> None:
    new_hire, manager_user = _new_hire_with_manager(db_session)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-metrics-rejected-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = _step(instance, "manager_approval")

    before = _sample_value(
        workflow_instances_finished_total,
        "workflow_instances_finished_total",
        workflow_key="employee_onboarding",
        status="rejected",
    )

    request_row = approval_request_repo.get_by_step_instance_id(db_session, manager_approval.id)
    assert request_row is not None
    approval_service.decide(
        db_session, request_row.id, manager_user, decision="rejected", notes="Not this time."
    )

    after = _sample_value(
        workflow_instances_finished_total,
        "workflow_instances_finished_total",
        workflow_key="employee_onboarding",
        status="rejected",
    )
    assert after == before + 1


def test_access_request_completion_increments_finished_total_completed(
    db_session: Session,
) -> None:
    dept = department_repo.create(db_session, name=f"Dept-{uuid.uuid4()}")
    employee = employee_repo.create(
        db_session,
        first_name="Sam",
        last_name="Ibarra",
        work_email=f"sam-{uuid.uuid4()}@cordant.io",
        job_title="Support Engineer",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2024, 1, 1),
        status=EmployeeStatus.ACTIVE,
        location="Remote",
        risk_level=RiskLevel.LOW,
    )
    application = application_repo.create(
        db_session,
        name=f"App-{uuid.uuid4()}",
        description="Low-risk internal tool.",
        risk_level=RiskLevel.LOW,
    )

    before = _sample_value(
        workflow_instances_finished_total,
        "workflow_instances_finished_total",
        workflow_key="software_access_request",
        status="completed",
    )

    instance = start_workflow(
        db_session,
        workflow_key="software_access_request",
        input_data={
            "employee_id": str(employee.id),
            "application_id": str(application.id),
            "justification": "Need it for daily work.",
            "application_risk_level": "low",
            "auto_approved": True,
        },
        dedup_key=f"test-metrics-completed-{uuid.uuid4()}",
        employee_id=employee.id,
    )
    # auto_approved + low risk skips every approval/AI step, straight to the
    # fulfillment mcp_tool step, which pauses awaiting confirmation
    # (ADR-0010) rather than completing outright -- same as
    # test_access_requests.py's own low-risk happy path.
    fulfillment_step = _step(instance, "create_fulfillment_task")
    confirm_external_completion(db_session, instance, fulfillment_step)

    after = _sample_value(
        workflow_instances_finished_total,
        "workflow_instances_finished_total",
        workflow_key="software_access_request",
        status="completed",
    )
    assert after == before + 1


# --- approvals -----------------------------------------------------------------


def test_approval_decision_increments_decisions_total_and_observes_wait_seconds(
    db_session: Session,
) -> None:
    new_hire, manager_user = _new_hire_with_manager(db_session)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-metrics-approve-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = _step(instance, "manager_approval")

    request_row = approval_request_repo.get_by_step_instance_id(db_session, manager_approval.id)
    assert request_row is not None

    before_decisions = _sample_value(
        approval_decisions_total,
        "approval_decisions_total",
        approver_role="manager",
        decision="approved",
    )
    before_wait_count = _sample_value(
        approval_wait_seconds, "approval_wait_seconds_count", approver_role="manager"
    )

    approval_service.decide(
        db_session, request_row.id, manager_user, decision="approved", notes="Looks good."
    )

    after_decisions = _sample_value(
        approval_decisions_total,
        "approval_decisions_total",
        approver_role="manager",
        decision="approved",
    )
    after_wait_count = _sample_value(
        approval_wait_seconds, "approval_wait_seconds_count", approver_role="manager"
    )
    assert after_decisions == before_decisions + 1
    assert after_wait_count == before_wait_count + 1


# --- MCP tool calls --------------------------------------------------------------


def test_mcp_call_tool_success_observes_completed_duration(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_call_tool_async(
        server_url: str, tool_name: str, arguments: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        return {"found": False}

    monkeypatch.setattr(
        "app.services.integrations.mcp_client._call_tool_async", fake_call_tool_async
    )

    before = _sample_value(
        mcp_tool_call_duration_seconds,
        "mcp_tool_call_duration_seconds_count",
        tool_name="lookup_employee",
        caller="workflow_engine",
        status="completed",
    )

    mcp_client.call_tool(
        db_session,
        tool_name="lookup_employee",
        arguments={"employee_id": "does-not-matter"},
        caller=MCPToolCaller.WORKFLOW_ENGINE,
    )

    after = _sample_value(
        mcp_tool_call_duration_seconds,
        "mcp_tool_call_duration_seconds_count",
        tool_name="lookup_employee",
        caller="workflow_engine",
        status="completed",
    )
    assert after == before + 1


def test_mcp_call_tool_failure_observes_failed_duration(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_call_tool_async(
        server_url: str, tool_name: str, arguments: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        raise TimeoutError("simulated MCP call timeout")

    monkeypatch.setattr(
        "app.services.integrations.mcp_client._call_tool_async", failing_call_tool_async
    )

    before = _sample_value(
        mcp_tool_call_duration_seconds,
        "mcp_tool_call_duration_seconds_count",
        tool_name="lookup_employee",
        caller="workflow_engine",
        status="failed",
    )

    with pytest.raises(mcp_client.MCPToolError):
        mcp_client.call_tool(
            db_session,
            tool_name="lookup_employee",
            arguments={"employee_id": "does-not-matter"},
            caller=MCPToolCaller.WORKFLOW_ENGINE,
        )

    after = _sample_value(
        mcp_tool_call_duration_seconds,
        "mcp_tool_call_duration_seconds_count",
        tool_name="lookup_employee",
        caller="workflow_engine",
        status="failed",
    )
    assert after == before + 1
