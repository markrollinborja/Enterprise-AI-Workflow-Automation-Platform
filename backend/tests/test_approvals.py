"""Covers the two things Phase 7 actually adds on top of Phase 6's engine:
who an approval gets assigned to (specific manager vs. role pool), and the
human-facing decide flow (authorization, recording a decision, resuming or
ending the underlying workflow instance) — both through the service layer
directly and through the real HTTP routes.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, PermissionDeniedError
from app.core.security import hash_password
from app.models.enums import (
    ApprovalRequestStatus,
    EmployeeStatus,
    EmploymentType,
    InstanceStatus,
    RiskLevel,
    UserRole,
)
from app.models.user import User
from app.repositories import approval_request_repo, department_repo, employee_repo
from app.services.approvals import service as approval_service
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import start_workflow

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


def _admin_user(db: Session) -> User:
    """Shorthand for the recurring "just give me an Administrator" need —
    used wherever a test needs *someone* authorized to decide an approval
    without caring who, specifically."""
    return _create_user(db, email=f"admin-{uuid.uuid4()}@cordant.io", role=UserRole.ADMINISTRATOR)


def _login(client: TestClient, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _auth_headers(client: TestClient, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _step(instance, key: str):
    return next(s for s in instance.step_instances if s.step_key == key)


def _new_hire_with_manager(db: Session, *, manager_has_login: bool):
    dept = department_repo.create(db, name=f"Dept-{uuid.uuid4()}")
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
    manager_user = None
    if manager_has_login:
        manager_user = _create_user(
            db, email=manager.work_email, role=UserRole.MANAGER, employee_id=manager.id
        )

    new_hire = employee_repo.create(
        db,
        first_name="Theo",
        last_name="Nakamura",
        work_email=f"theo-{uuid.uuid4()}@cordant.io",
        job_title="Software Engineer",
        department_id=dept.id,
        manager_id=manager.id,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 8, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )
    return new_hire, manager, manager_user


def test_manager_approval_assigned_to_specific_manager(db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-approval-assign-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )

    approval_request = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    assert approval_request is not None
    assert approval_request.assigned_user_id == manager_user.id
    assert approval_request.approver_role == UserRole.MANAGER
    assert approval_request.status == ApprovalRequestStatus.PENDING


def test_manager_approval_falls_back_to_pool_when_manager_has_no_login(
    db_session: Session,
) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=False)
    assert manager_user is None

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-approval-nofallback-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )

    approval_request = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    assert approval_request is not None
    assert approval_request.assigned_user_id is None
    assert approval_request.approver_role == UserRole.MANAGER


def test_it_review_is_role_pool_not_assigned_to_anyone(db_session: Session) -> None:
    new_hire, _manager, _manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-it-pool-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    approval_service.decide(
        db_session,
        manager_approval.id,
        _admin_user(db_session),
        decision="approved",
    )

    db_session.refresh(instance)
    it_review = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "it_review_access").id
    )
    assert it_review is not None
    assert it_review.assigned_user_id is None
    assert it_review.approver_role == UserRole.IT


def test_inbox_only_shows_assigned_approval_to_the_assigned_user(db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    other_manager = _create_user(
        db_session, email=f"other-mgr-{uuid.uuid4()}@cordant.io", role=UserRole.MANAGER
    )

    start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-inbox-assigned-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )

    assigned_inbox = approval_request_repo.list_pending_for_user(db_session, manager_user)
    assert len(assigned_inbox) == 1

    unrelated_inbox = approval_request_repo.list_pending_for_user(db_session, other_manager)
    assert unrelated_inbox == []


def test_inbox_shows_role_pool_approval_to_any_user_with_that_role(db_session: Session) -> None:
    new_hire, _manager, _manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-inbox-pool-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    admin = _admin_user(db_session)
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    approval_service.decide(db_session, manager_approval.id, admin, decision="approved")

    it_user_a = _create_user(db_session, email=f"it-a-{uuid.uuid4()}@cordant.io", role=UserRole.IT)
    it_user_b = _create_user(db_session, email=f"it-b-{uuid.uuid4()}@cordant.io", role=UserRole.IT)
    assert len(approval_request_repo.list_pending_for_user(db_session, it_user_a)) == 1
    assert len(approval_request_repo.list_pending_for_user(db_session, it_user_b)) == 1


def test_administrator_sees_all_pending_approvals(db_session: Session) -> None:
    new_hire, _manager, _manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-admin-all-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    admin = _admin_user(db_session)
    assert len(approval_request_repo.list_pending_for_user(db_session, admin)) == 1


def test_decide_approved_resumes_the_workflow(db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-decide-approve-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )

    response = approval_service.decide(
        db_session, manager_approval.id, manager_user, decision="approved", notes="Looks good."
    )
    assert response.status == "approved"

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.WAITING_APPROVAL  # now paused at it_review_access


def test_decide_rejected_ends_the_workflow(db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-decide-reject-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )

    approval_service.decide(
        db_session, manager_approval.id, manager_user, decision="rejected", notes="Not this time."
    )

    db_session.refresh(instance)
    assert instance.status == InstanceStatus.REJECTED


def test_decide_by_unrelated_user_is_forbidden(db_session: Session) -> None:
    new_hire, _manager, _manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-decide-wrong-user-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    unrelated_manager = _create_user(
        db_session, email=f"unrelated-{uuid.uuid4()}@cordant.io", role=UserRole.MANAGER
    )

    with pytest.raises(PermissionDeniedError):
        approval_service.decide(
            db_session, manager_approval.id, unrelated_manager, decision="approved"
        )


def test_decide_by_wrong_role_is_forbidden(db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-decide-wrong-role-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    admin = _admin_user(db_session)
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    approval_service.decide(db_session, manager_approval.id, manager_user, decision="approved")

    db_session.refresh(instance)
    it_review = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "it_review_access").id
    )
    security_role_user = _create_user(
        db_session, email=f"security-{uuid.uuid4()}@cordant.io", role=UserRole.SECURITY
    )

    with pytest.raises(PermissionDeniedError):
        approval_service.decide(db_session, it_review.id, security_role_user, decision="approved")

    # Sanity check the fixture didn't accidentally not-need admin.
    assert admin.role == UserRole.ADMINISTRATOR


def test_decide_twice_raises_conflict(db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-decide-conflict-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    approval_service.decide(db_session, manager_approval.id, manager_user, decision="approved")

    with pytest.raises(ConflictError):
        approval_service.decide(db_session, manager_approval.id, manager_user, decision="approved")


def test_list_approvals_route_requires_auth(client: TestClient) -> None:
    response = client.get("/approvals")
    assert response.status_code == 403


def test_decide_route_full_round_trip(client: TestClient, db_session: Session) -> None:
    new_hire, _manager, manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-route-roundtrip-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )

    token = _login(client, manager_user.email)
    headers = _auth_headers(client, token)

    inbox_response = client.get("/approvals", headers=headers)
    assert inbox_response.status_code == 200
    assert any(item["id"] == str(manager_approval.id) for item in inbox_response.json())

    decide_response = client.post(
        f"/approvals/{manager_approval.id}/decide",
        headers=headers,
        json={"decision": "approved", "notes": "Approved via API."},
    )
    assert decide_response.status_code == 200
    assert decide_response.json()["status"] == "approved"


def test_decide_route_rejects_role_without_approval_authority(
    client: TestClient, db_session: Session
) -> None:
    new_hire, _manager, _manager_user = _new_hire_with_manager(db_session, manager_has_login=True)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-route-forbidden-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    employee_user = _create_user(
        db_session, email=f"plain-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE
    )
    token = _login(client, employee_user.email)

    response = client.post(
        f"/approvals/{manager_approval.id}/decide",
        headers=_auth_headers(client, token),
        json={"decision": "approved"},
    )
    assert response.status_code == 403
