"""Covers Phase 8's actual new surface: the rules engine composed with the
workflow engine through the real /access-requests route and service — not
just the pure-function rules tests in test_rules.py. Confirms the two
demoable branches end to end: a LOW-risk request auto-approves and runs to
completion with no human in the loop, while a HIGH-risk request correctly
skips auto-approval and pauses at manager_approval, same as onboarding's
approval pause.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.application import Application
from app.models.employee import Employee
from app.models.enums import (
    EmployeeStatus,
    EmploymentType,
    InstanceStatus,
    RiskLevel,
    UserRole,
)
from app.models.user import User
from app.repositories import application_repo, department_repo, employee_repo
from app.schemas.access_request import AccessRequestCreate
from app.services.access_requests import service as access_request_service
from app.services.workflows.definition_loader import load_all_definitions

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


def _employee_with_login(db: Session, *, risk_level: RiskLevel) -> tuple[Employee, User]:
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
        risk_level=risk_level,
    )
    user = _create_user(
        db, email=employee.work_email, role=UserRole.EMPLOYEE, employee_id=employee.id
    )
    return employee, user


def _application(db: Session, *, risk_level: RiskLevel) -> Application:
    return application_repo.create(
        db,
        name=f"App-{uuid.uuid4()}",
        description="Test application.",
        risk_level=risk_level,
    )


def _login(client: TestClient, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _auth_headers(client: TestClient, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_low_risk_request_is_auto_approved_and_runs_to_completion(db_session: Session) -> None:
    _employee, user = _employee_with_login(db_session, risk_level=RiskLevel.LOW)
    application = _application(db_session, risk_level=RiskLevel.LOW)

    response = access_request_service.submit_access_request(
        db_session,
        AccessRequestCreate(
            application_id=application.id, justification="Need it for daily engineering work."
        ),
        current_user=user,
    )

    assert response.computed_risk_level == RiskLevel.LOW
    assert response.auto_approved is True
    # No approval step ever paused it, and the (mocked, per conftest.py's
    # autouse MCP fixture) mcp_tool steps always succeed — the instance
    # should run straight through to completion with zero human involvement.
    assert response.status == InstanceStatus.COMPLETED
    assert response.current_step_key is None


def test_high_risk_request_is_not_auto_approved_and_waits_on_manager(
    db_session: Session,
) -> None:
    _employee, user = _employee_with_login(db_session, risk_level=RiskLevel.LOW)
    application = _application(db_session, risk_level=RiskLevel.HIGH)

    response = access_request_service.submit_access_request(
        db_session,
        AccessRequestCreate(
            application_id=application.id,
            justification="Need production access to investigate an incident.",
        ),
        current_user=user,
    )

    # "highest wins": a low-risk employee requesting a high-risk application
    # is still a high-risk request (see classify_request_risk).
    assert response.computed_risk_level == RiskLevel.HIGH
    assert response.auto_approved is False
    assert response.status == InstanceStatus.WAITING_APPROVAL
    assert response.current_step_key == "manager_approval"


def test_submit_without_linked_employee_raises_conflict(db_session: Session) -> None:
    user = _create_user(
        db_session, email=f"no-employee-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE
    )
    application = _application(db_session, risk_level=RiskLevel.LOW)

    with pytest.raises(ConflictError):
        access_request_service.submit_access_request(
            db_session,
            AccessRequestCreate(application_id=application.id, justification="Doesn't matter."),
            current_user=user,
        )


def test_submit_with_unknown_application_raises_not_found(db_session: Session) -> None:
    _employee, user = _employee_with_login(db_session, risk_level=RiskLevel.LOW)

    with pytest.raises(NotFoundError):
        access_request_service.submit_access_request(
            db_session,
            AccessRequestCreate(application_id=uuid.uuid4(), justification="Doesn't matter."),
            current_user=user,
        )


def test_route_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/access-requests", json={"application_id": str(uuid.uuid4()), "justification": "x" * 20}
    )
    assert response.status_code == 403


def test_route_full_round_trip_auto_approves_low_risk(
    client: TestClient, db_session: Session
) -> None:
    _employee, user = _employee_with_login(db_session, risk_level=RiskLevel.LOW)
    application = _application(db_session, risk_level=RiskLevel.LOW)
    token = _login(client, user.email)

    response = client.post(
        "/access-requests",
        headers=_auth_headers(client, token),
        json={
            "application_id": str(application.id),
            "justification": "Need it for daily engineering work.",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_approved"] is True
    assert body["computed_risk_level"] == "low"
    assert body["status"] == "completed"
    assert body["application_name"] == application.name
