"""Covers /webhooks/jira end to end (ADR-0010, Phase 10 checkpoint 3):
signature verification, correlating an inbound issue key back to the
WorkflowStepInstance that created it, confirming fulfillment through the
real engine (not a mocked confirm_external_completion), and the
idempotency behavior a webhook endpoint actually needs (a duplicate
delivery is ignored with 200, never a 409 — see the route's own
docstring).

Drives the low-risk software_access_request path to reach
create_fulfillment_task's WAITING_EXTERNAL pause — the fewest steps to a
real awaits_fulfillment step (no approval, no AI step to mock beyond the
autouse fixtures conftest.py already provides for every test).
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import (
    EmployeeStatus,
    EmploymentType,
    InstanceStatus,
    RiskLevel,
    StepStatus,
    UserRole,
)
from app.models.user import User
from app.models.workflow import WorkflowInstance
from app.repositories import application_repo, department_repo, employee_repo
from app.schemas.access_request import AccessRequestCreate
from app.services.access_requests import service as access_request_service
from app.services.workflows.definition_loader import load_all_definitions

TEST_PASSWORD = "CorrectHorse123!"
TEST_SECRET = "test-jira-webhook-secret"


@pytest.fixture(autouse=True)
def _load_definitions(db_session: Session) -> None:
    load_all_definitions(db_session)


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A real secret by default, so the happy-path/ignored-outcome tests
    aren't also implicitly testing "not configured" — that gets its own
    dedicated test, which overrides this back to blank."""
    get_settings.cache_clear()
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", TEST_SECRET)
    yield
    get_settings.cache_clear()


def _low_risk_instance_awaiting_fulfillment(db: Session) -> WorkflowInstance:
    """Low risk auto-approves with no approval pause and skips
    summarize_justification (condition: risk != low) — the shortest real
    path to create_fulfillment_task's WAITING_EXTERNAL pause. Same setup
    shape as test_access_requests.py's low-risk test."""
    dept = department_repo.create(db, name=f"Dept-{uuid.uuid4()}")
    employee = employee_repo.create(
        db,
        first_name="Riley",
        last_name="Chen",
        work_email=f"riley-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2024, 1, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    user = User(
        email=employee.work_email,
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Riley Chen",
        role=UserRole.EMPLOYEE,
        employee_id=employee.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    application = application_repo.create(
        db,
        name=f"App-{uuid.uuid4()}",
        description="Test application.",
        risk_level=RiskLevel.LOW,
    )

    response = access_request_service.submit_access_request(
        db,
        AccessRequestCreate(
            application_id=application.id, justification="Need it for daily engineering work."
        ),
        current_user=user,
    )
    instance = db.get(WorkflowInstance, response.workflow_instance_id)
    assert instance is not None
    assert instance.status == InstanceStatus.WAITING_EXTERNAL
    return instance


def _fulfillment_step(instance: WorkflowInstance):
    return next(
        s for s in instance.step_instances if s.step_key == "create_fulfillment_task"
    )


def _signed_payload(
    *, issue_key: str, status_name: str, secret: str = TEST_SECRET
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": issue_key, "fields": {"status": {"name": status_name}}},
        }
    ).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {"content-type": "application/json", "x-hub-signature-256": f"sha256={digest}"}
    return body, headers


def test_confirmed_webhook_completes_the_step_and_advances_the_workflow(
    client: TestClient, db_session: Session
) -> None:
    instance = _low_risk_instance_awaiting_fulfillment(db_session)
    step = _fulfillment_step(instance)
    assert step.status == StepStatus.WAITING_EXTERNAL
    issue_key = step.external_ref
    assert issue_key is not None

    body, headers = _signed_payload(issue_key=issue_key, status_name="Done")
    response = client.post("/webhooks/jira", content=body, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "confirmed", "issue_key": issue_key}

    db_session.expire_all()
    refreshed = db_session.get(WorkflowInstance, instance.id)
    assert refreshed is not None
    # notify_employee (mcp_tool, failure_behavior=continue) is the only
    # step left after create_fulfillment_task — it succeeds in mock mode,
    # so the whole instance completes.
    assert refreshed.status == InstanceStatus.COMPLETED
    assert _fulfillment_step(refreshed).status == StepStatus.COMPLETED


def test_missing_signature_header_is_rejected(client: TestClient, db_session: Session) -> None:
    instance = _low_risk_instance_awaiting_fulfillment(db_session)
    issue_key = _fulfillment_step(instance).external_ref
    assert issue_key is not None
    body, _headers = _signed_payload(issue_key=issue_key, status_name="Done")

    response = client.post(
        "/webhooks/jira", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 401
    db_session.expire_all()
    refreshed = db_session.get(WorkflowInstance, instance.id)
    assert refreshed is not None
    # Rejected before ever touching engine state.
    assert refreshed.status == InstanceStatus.WAITING_EXTERNAL


def test_wrong_signature_is_rejected(client: TestClient, db_session: Session) -> None:
    instance = _low_risk_instance_awaiting_fulfillment(db_session)
    issue_key = _fulfillment_step(instance).external_ref
    assert issue_key is not None
    # Signed with a different secret than the one the app is configured
    # with (TEST_SECRET) — a well-formed signature that just doesn't match.
    body, headers = _signed_payload(issue_key=issue_key, status_name="Done", secret="wrong")

    response = client.post("/webhooks/jira", content=body, headers=headers)

    assert response.status_code == 401


def test_no_secret_configured_rejects_every_request(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = _low_risk_instance_awaiting_fulfillment(db_session)
    issue_key = _fulfillment_step(instance).external_ref
    assert issue_key is not None

    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    body, headers = _signed_payload(issue_key=issue_key, status_name="Done")

    response = client.post("/webhooks/jira", content=body, headers=headers)

    assert response.status_code == 401
    get_settings.cache_clear()


def test_non_done_status_is_ignored(client: TestClient, db_session: Session) -> None:
    instance = _low_risk_instance_awaiting_fulfillment(db_session)
    issue_key = _fulfillment_step(instance).external_ref
    assert issue_key is not None
    body, headers = _signed_payload(issue_key=issue_key, status_name="In Progress")

    response = client.post("/webhooks/jira", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    db_session.expire_all()
    refreshed = db_session.get(WorkflowInstance, instance.id)
    assert refreshed is not None
    assert refreshed.status == InstanceStatus.WAITING_EXTERNAL


def test_unknown_issue_key_is_ignored(client: TestClient, db_session: Session) -> None:
    _low_risk_instance_awaiting_fulfillment(db_session)
    body, headers = _signed_payload(issue_key="ACC-99999", status_name="Done")

    response = client.post("/webhooks/jira", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ignored",
        "reason": "no workflow step tracking this issue",
    }


def test_duplicate_delivery_is_ignored_not_erroring(
    client: TestClient, db_session: Session
) -> None:
    instance = _low_risk_instance_awaiting_fulfillment(db_session)
    issue_key = _fulfillment_step(instance).external_ref
    assert issue_key is not None
    body, headers = _signed_payload(issue_key=issue_key, status_name="Done")

    first = client.post("/webhooks/jira", content=body, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "confirmed"

    second = client.post("/webhooks/jira", content=body, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "ignored"


def test_malformed_json_is_ignored(client: TestClient) -> None:
    secret = TEST_SECRET
    body = b"not valid json"
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    response = client.post(
        "/webhooks/jira",
        content=body,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": f"sha256={digest}",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
