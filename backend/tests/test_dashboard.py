"""Covers Phase 12's read-only dashboard surface: GET /dashboard/summary,
GET /workflow-instances (+ ?status=, + /{id}), and GET /audit-log — all
Administrator-only (section 9 of the project spec). Drives one real
onboarding instance through both approvals, a real (mocked) AI call, and
all three MCP tool steps to completion — reusing the same engine/approvals/
AI/MCP wiring test_workflow_engine.py and test_approvals.py already
exercise — so the detail and timeline responses have real approvals, AI
output, MCP calls, and notifications to assert against, not fixtures
standing in for them. A second, minimal instance covers the failed-workflow
path (test_workflow_engine.py's own validation-failure setup).
"""

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models.enums import (
    EmployeeStatus,
    EmploymentType,
    InstanceStatus,
    RiskLevel,
    UserRole,
)
from app.models.user import User
from app.models.workflow import WorkflowInstance
from app.repositories import (
    access_package_repo,
    approval_request_repo,
    department_repo,
    employee_repo,
)
from app.services.approvals import service as approval_service
from app.services.dashboard import service as dashboard_service
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import confirm_external_completion, start_workflow

TEST_PASSWORD = "CorrectHorse123!"


@pytest.fixture(autouse=True)
def _load_definitions(db_session: Session) -> None:
    load_all_definitions(db_session)


def _create_user(
    db: Session, *, email: str, role: UserRole, employee_id: uuid.UUID | None = None
) -> User:
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


def _login(client: TestClient, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _auth_headers(client: TestClient, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _step(instance: WorkflowInstance, key: str):
    return next(s for s in instance.step_instances if s.step_key == key)


class _FakeRecommendation(BaseModel):
    recommended_package_name: str
    confidence_score: float
    explanation: str
    missing_information: list[str] = []


def _mock_recommendation(
    monkeypatch: pytest.MonkeyPatch, *, package_name: str, confidence: float
) -> None:
    """Same fixture shape as test_workflow_engine.py's own helper — see
    that file for why this is how AI is mocked at the engine level."""
    parsed = _FakeRecommendation(
        recommended_package_name=package_name,
        confidence_score=confidence,
        explanation="Mocked for dashboard test.",
    )
    fake_completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(parsed=parsed, refusal=None, tool_calls=None, content=None)
            )
        ],
        usage=SimpleNamespace(total_tokens=42),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kwargs: fake_completion))
    )
    monkeypatch.setattr("app.services.ai.service._client", lambda: fake_client)


def _completed_onboarding_instance(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> tuple[WorkflowInstance, User, User]:
    """A full onboarding instance driven to real completion: manager
    approval, then it_review_access (low AI confidence forces the pause),
    then all three MCP tool steps including the Jira fulfillment
    confirmation. Uses approval_service.decide (not resume_workflow_step
    directly) so real ApprovalDecision rows exist — the dashboard's audit
    timeline and detail view need those, unlike test_workflow_engine.py's
    own engine-mechanics-only tests. Returns (instance, hr_submitter,
    manager_user)."""
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
    manager = employee_repo.create(
        db,
        first_name="Mona",
        last_name="Reyes",
        work_email=f"mona-{uuid.uuid4()}@cordant.io",
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
        first_name="Jamie",
        last_name="Rivera",
        work_email=f"jamie-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=manager.id,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 8, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    hr_submitter = _create_user(db, email=f"hr-{uuid.uuid4()}@cordant.io", role=UserRole.HR)
    admin = _create_user(
        db, email=f"admin-review-{uuid.uuid4()}@cordant.io", role=UserRole.ADMINISTRATOR
    )

    _mock_recommendation(monkeypatch, package_name=package_name, confidence=0.4)

    instance = start_workflow(
        db,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-dashboard-onboarding-{uuid.uuid4()}",
        employee_id=new_hire.id,
        initiated_by_user_id=hr_submitter.id,
    )

    manager_approval = approval_request_repo.get_by_step_instance_id(
        db, _step(instance, "manager_approval").id
    )
    approval_service.decide(
        db, manager_approval.id, manager_user, decision="approved", notes="Looks good."
    )
    db.refresh(instance)

    it_review = approval_request_repo.get_by_step_instance_id(
        db, _step(instance, "it_review_access").id
    )
    approval_service.decide(db, it_review.id, admin, decision="approved")
    db.refresh(instance)

    instance = confirm_external_completion(db, instance, _step(instance, "create_it_tasks"))
    return instance, hr_submitter, manager_user


def _failed_instance(db: Session) -> WorkflowInstance:
    """Same minimal setup as test_workflow_engine.py's
    test_validation_failure_fails_the_workflow_immediately — missing
    employee_id fails validate_employee immediately, no mocking needed."""
    return start_workflow(
        db,
        workflow_key="employee_onboarding",
        input_data={},
        dedup_key=f"test-dashboard-failed-{uuid.uuid4()}",
    )


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


def test_summary_counts_and_aggregates_reflect_real_instances(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, _hr, _manager = _completed_onboarding_instance(db_session, monkeypatch)
    _failed_instance(db_session)

    summary = dashboard_service.get_summary(db_session)

    assert summary.completed_workflows >= 1
    assert summary.failed_workflows >= 1
    assert summary.avg_completion_seconds is not None
    assert summary.avg_completion_seconds >= 0
    assert summary.requests_by_type.get("Employee Onboarding", 0) >= 2
    dept_name = instance.employee.department.name
    assert summary.requests_by_department.get(dept_name, 0) >= 1


def test_summary_avg_completion_is_none_with_no_completed_instances(
    db_session: Session,
) -> None:
    _failed_instance(db_session)
    summary = dashboard_service.get_summary(db_session)
    assert summary.avg_completion_seconds is None


# ---------------------------------------------------------------------------
# list_workflow_instances
# ---------------------------------------------------------------------------


def test_list_workflow_instances_includes_completed_instance(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, hr_submitter, _manager = _completed_onboarding_instance(db_session, monkeypatch)

    rows = dashboard_service.list_workflow_instances(db_session)
    row = next(r for r in rows if r.id == instance.id)

    assert row.status == "completed"
    assert row.workflow_key == "employee_onboarding"
    assert row.initiated_by_name == hr_submitter.full_name
    assert row.employee_name is not None
    assert row.failed_step_key is None


def test_list_workflow_instances_filtered_to_failed_exposes_failure_detail(
    db_session: Session,
) -> None:
    failed = _failed_instance(db_session)

    rows = dashboard_service.list_workflow_instances(db_session, status=InstanceStatus.FAILED)

    assert all(r.status == "failed" for r in rows)
    row = next(r for r in rows if r.id == failed.id)
    assert row.failed_step_key == "validate_employee"
    assert row.failure_reason is not None
    assert "employee_id" in row.failure_reason
    assert row.failed_attempt_count is not None and row.failed_attempt_count >= 1


# ---------------------------------------------------------------------------
# get_workflow_instance_detail
# ---------------------------------------------------------------------------


def test_workflow_instance_detail_includes_every_section(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, hr_submitter, manager_user = _completed_onboarding_instance(
        db_session, monkeypatch
    )

    detail = dashboard_service.get_workflow_instance_detail(db_session, instance.id)

    assert detail.status == "completed"
    assert detail.initiated_by_name == hr_submitter.full_name
    assert {s.step_key for s in detail.steps} >= {
        "validate_employee",
        "manager_approval",
        "recommend_access",
        "it_review_access",
        "create_it_tasks",
        "schedule_orientation",
        "notify_slack",
    }

    assert len(detail.approvals) == 2
    manager_approval = next(a for a in detail.approvals if a.step_key == "manager_approval")
    assert manager_approval.decisions[0].decided_by_name == manager_user.full_name
    assert manager_approval.decisions[0].decision == "approved"

    assert len(detail.ai_executions) == 1
    assert detail.ai_executions[0].task_type == "recommend_access_package"

    mcp_tool_names = {e.tool_name for e in detail.mcp_tool_executions}
    assert mcp_tool_names == {
        "create_jira_task",
        "schedule_calendar_event",
        "send_slack_notification",
    }

    # Notifications: manager gets APPROVAL_REQUESTED (in-app + Slack), HR
    # submitter gets WORKFLOW_COMPLETED (in-app only) — see
    # test_notifications.py for the dedicated notification-wiring tests;
    # this just confirms the detail view surfaces them.
    assert any(n.type == "approval_requested" for n in detail.notifications)
    assert any(n.type == "workflow_completed" for n in detail.notifications)

    assert len(detail.audit_timeline) > 0
    timestamps = [e.timestamp for e in detail.audit_timeline]
    assert timestamps == sorted(timestamps)
    actions = {e.action for e in detail.audit_timeline}
    assert "workflow_started" in actions
    assert "approval_requested" in actions
    assert "approval_approved" in actions
    assert "ai_call_completed" in actions
    assert "integration_call_completed" in actions
    assert "workflow_completed" in actions


def test_workflow_instance_detail_unknown_id_raises_not_found(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        dashboard_service.get_workflow_instance_detail(db_session, uuid.uuid4())


def test_failed_instance_detail_audit_timeline_shows_failure(db_session: Session) -> None:
    failed = _failed_instance(db_session)
    detail = dashboard_service.get_workflow_instance_detail(db_session, failed.id)

    failure_entry = next(e for e in detail.audit_timeline if e.action == "workflow_failed")
    assert failure_entry.outcome == "failure"
    assert failure_entry.metadata["failed_step_key"] == "validate_employee"


# ---------------------------------------------------------------------------
# build_audit_timeline (global)
# ---------------------------------------------------------------------------


def test_global_audit_timeline_is_chronological_across_instances(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _completed_onboarding_instance(db_session, monkeypatch)
    _failed_instance(db_session)

    entries = dashboard_service.build_audit_timeline(db_session)

    assert len(entries) > 0
    timestamps = [e.timestamp for e in entries]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Routes: admin-only gating + wiring
# ---------------------------------------------------------------------------


def _employee_user(db: Session) -> User:
    return _create_user(db, email=f"plain-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE)


def _admin_user(db: Session) -> User:
    return _create_user(db, email=f"admin-{uuid.uuid4()}@cordant.io", role=UserRole.ADMINISTRATOR)


@pytest.mark.parametrize(
    "path",
    ["/dashboard/summary", "/workflow-instances", "/audit-log"],
)
def test_dashboard_routes_require_admin(
    client: TestClient, db_session: Session, path: str
) -> None:
    non_admin = _employee_user(db_session)
    token = _login(client, non_admin.email)

    response = client.get(path, headers=_auth_headers(client, token))
    assert response.status_code == 403


def test_dashboard_routes_require_auth(client: TestClient) -> None:
    assert client.get("/dashboard/summary").status_code == 403
    assert client.get("/workflow-instances").status_code == 403
    assert client.get("/audit-log").status_code == 403


def test_dashboard_summary_route_admin_round_trip(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _completed_onboarding_instance(db_session, monkeypatch)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.get("/dashboard/summary", headers=_auth_headers(client, token))
    assert response.status_code == 200
    assert response.json()["completed_workflows"] >= 1


def test_workflow_instances_route_status_filter(
    client: TestClient, db_session: Session
) -> None:
    failed = _failed_instance(db_session)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.get(
        "/workflow-instances", params={"status": "failed"}, headers=_auth_headers(client, token)
    )
    assert response.status_code == 200
    body = response.json()
    assert all(row["status"] == "failed" for row in body)
    assert any(row["id"] == str(failed.id) for row in body)


def test_workflow_instance_detail_route_admin_round_trip(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance, _hr, _manager = _completed_onboarding_instance(db_session, monkeypatch)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.get(
        f"/workflow-instances/{instance.id}", headers=_auth_headers(client, token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_workflow_instance_detail_route_unknown_id_is_404(
    client: TestClient, db_session: Session
) -> None:
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.get(
        f"/workflow-instances/{uuid.uuid4()}", headers=_auth_headers(client, token)
    )
    assert response.status_code == 404


def test_audit_log_route_admin_round_trip(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _completed_onboarding_instance(db_session, monkeypatch)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.get("/audit-log", headers=_auth_headers(client, token))
    assert response.status_code == 200
    assert len(response.json()) > 0


# ---------------------------------------------------------------------------
# POST /workflow-instances/{id}/steps/{step_key}/retry (Phase 13b) —
# actually defined in api/routes/workflow_instances.py, not dashboard.py,
# but tested here alongside the rest of the /workflow-instances surface,
# reusing this file's admin/login fixtures rather than duplicating them.
# ---------------------------------------------------------------------------


def test_retry_route_requires_admin(client: TestClient, db_session: Session) -> None:
    failed = _failed_instance(db_session)
    non_admin = _employee_user(db_session)
    token = _login(client, non_admin.email)

    response = client.post(
        f"/workflow-instances/{failed.id}/steps/validate_employee/retry",
        headers=_auth_headers(client, token),
    )
    assert response.status_code == 403


def test_retry_route_unknown_instance_is_404(client: TestClient, db_session: Session) -> None:
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.post(
        f"/workflow-instances/{uuid.uuid4()}/steps/validate_employee/retry",
        headers=_auth_headers(client, token),
    )
    assert response.status_code == 404


def test_retry_route_unknown_step_key_is_404(client: TestClient, db_session: Session) -> None:
    failed = _failed_instance(db_session)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.post(
        f"/workflow-instances/{failed.id}/steps/not_a_real_step/retry",
        headers=_auth_headers(client, token),
    )
    assert response.status_code == 404


def test_retry_route_on_failed_step_reruns_it_and_records_who(
    client: TestClient, db_session: Session
) -> None:
    """validate_employee fails immediately on a missing employee_id
    (`_failed_instance`'s setup) — the retry route can't fix that input
    itself (see test_workflow_engine.py's service-level test for the
    "actually reaches success" case), so this asserts what the route layer
    owns: it's reachable by an admin, and a retry call updates the response
    body's step detail. Retrying twice in a row is legitimately allowed
    here, not a 409 — the same unfixed root cause fails again each time,
    landing back on FAILED, which is retryable again by design (that's the
    whole feature); test_retry_route_on_non_failed_step_is_409 below covers
    the actual rejection case, a step that was never FAILED to begin with.
    """
    failed = _failed_instance(db_session)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.post(
        f"/workflow-instances/{failed.id}/steps/validate_employee/retry",
        headers=_auth_headers(client, token),
    )
    assert response.status_code == 200
    body = response.json()
    step = next(s for s in body["steps"] if s["step_key"] == "validate_employee")
    assert step["retried_by_name"] == admin.full_name
    assert step["retried_at"] is not None
    # Same underlying problem, still unfixed -> fails again immediately ->
    # back to FAILED, not left at PENDING/RUNNING.
    assert step["status"] == "failed"
    assert body["status"] == "failed"

    # Retrying again is allowed — FAILED is FAILED regardless of how it
    # got there — and increments attempt_count again rather than erroring.
    second = client.post(
        f"/workflow-instances/{failed.id}/steps/validate_employee/retry",
        headers=_auth_headers(client, token),
    )
    assert second.status_code == 200
    second_step = next(
        s for s in second.json()["steps"] if s["step_key"] == "validate_employee"
    )
    assert second_step["attempt_count"] == step["attempt_count"] + 1


def test_retry_route_on_non_failed_step_is_409(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual rejection case retry_failed_step guards: a step that was
    never FAILED at all. Uses a completed onboarding instance's
    manager_approval step, which is COMPLETED, not FAILED."""
    instance, _hr, _manager = _completed_onboarding_instance(db_session, monkeypatch)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    response = client.post(
        f"/workflow-instances/{instance.id}/steps/manager_approval/retry",
        headers=_auth_headers(client, token),
    )
    assert response.status_code == 409


def test_retry_route_appears_in_audit_timeline(client: TestClient, db_session: Session) -> None:
    failed = _failed_instance(db_session)
    admin = _admin_user(db_session)
    token = _login(client, admin.email)

    client.post(
        f"/workflow-instances/{failed.id}/steps/validate_employee/retry",
        headers=_auth_headers(client, token),
    )

    response = client.get(
        f"/workflow-instances/{failed.id}", headers=_auth_headers(client, token)
    )
    entry = next(
        e for e in response.json()["audit_timeline"] if e["action"] == "step_manually_retried"
    )
    assert entry["actor"] == admin.full_name
    assert entry["metadata"]["step_key"] == "validate_employee"
