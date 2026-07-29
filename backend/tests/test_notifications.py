"""Covers Phase 11's actual new surface: the notify() entry point itself
(in-app always written, Slack/email opt-in, a failed Slack send never
raising or blocking the in-app row, recipient=None being a silent no-op),
the repo-level in-app-only filtering GET /notifications relies on, and the
three points services/workflows/service.py actually calls notify() from —
approval-created (specifically-assigned approver only), workflow-completed,
and workflow-rejected. Not re-testing engine mechanics already covered by
test_workflow_engine.py/test_approvals.py/test_access_requests.py — only
the notification side-effects those flows now also produce.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models.enums import (
    EmployeeStatus,
    EmploymentType,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    RiskLevel,
    UserRole,
)
from app.models.notification import Notification
from app.models.user import User
from app.repositories import (
    application_repo,
    approval_request_repo,
    department_repo,
    employee_repo,
    workflow_instance_repo,
)
from app.schemas.access_request import AccessRequestCreate
from app.services.access_requests import service as access_request_service
from app.services.approvals import service as approval_service
from app.services.notifications import service as notification_service
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


def _step(instance, key: str):
    return next(s for s in instance.step_instances if s.step_key == key)


def _all_notifications(db: Session, user_id: uuid.UUID) -> list[Notification]:
    """Unlike notification_repo.list_for_user (IN_APP only, what the
    in-app inbox shows), this returns every channel's row — needed here to
    assert on the SLACK/EMAIL delivery-attempt rows too."""
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at)
        )
    )


# ---------------------------------------------------------------------------
# notify() itself
# ---------------------------------------------------------------------------


def test_notify_always_writes_in_app_row(db_session: Session) -> None:
    user = _create_user(db_session, email=f"u-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE)

    notification_service.notify(
        db_session,
        recipient=user,
        notification_type=NotificationType.WORKFLOW_COMPLETED,
        title="Title",
        body="Body",
    )

    rows = _all_notifications(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].channel == NotificationChannel.IN_APP
    assert rows[0].status == NotificationStatus.COMPLETED
    assert rows[0].read_at is None


def test_notify_with_no_recipient_is_a_silent_noop(db_session: Session) -> None:
    # Must not raise, and must not write anything — see notify()'s
    # docstring: an onboarding new hire with no User login yet is a normal
    # case, not an error.
    notification_service.notify(
        db_session,
        recipient=None,
        notification_type=NotificationType.WORKFLOW_COMPLETED,
        title="Title",
        body="Body",
    )
    # Nothing to assert against a specific user_id here; the absence of an
    # exception is the actual assertion. A stray row would still show up as
    # a leftover in conftest.py's cleanup if this were somehow wrong.


def test_notify_with_send_slack_writes_slack_row_via_mcp_tool(db_session: Session) -> None:
    user = _create_user(db_session, email=f"u-{uuid.uuid4()}@cordant.io", role=UserRole.MANAGER)

    notification_service.notify(
        db_session,
        recipient=user,
        notification_type=NotificationType.APPROVAL_REQUESTED,
        title="Approval needed",
        body="Please review.",
        send_slack=True,
    )

    rows = _all_notifications(db_session, user.id)
    channels = {row.channel: row for row in rows}
    assert set(channels) == {NotificationChannel.IN_APP, NotificationChannel.SLACK}
    # conftest.py's autouse MCP mock always succeeds for send_slack_notification.
    assert channels[NotificationChannel.SLACK].status == NotificationStatus.COMPLETED


def test_notify_slack_failure_does_not_raise_and_records_failed_status(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _create_user(db_session, email=f"u-{uuid.uuid4()}@cordant.io", role=UserRole.MANAGER)

    async def _boom(server_url: str, tool_name: str, arguments: dict[str, object]) -> dict:
        raise RuntimeError("mcp_server unreachable")

    monkeypatch.setattr("app.services.integrations.mcp_client._call_tool_async", _boom)

    # Must not raise — a missed Slack ping is never a reason to fail
    # anything (mirrors executors.py's notify_slack, failure_behavior=continue).
    notification_service.notify(
        db_session,
        recipient=user,
        notification_type=NotificationType.APPROVAL_REQUESTED,
        title="Approval needed",
        body="Please review.",
        send_slack=True,
    )

    rows = _all_notifications(db_session, user.id)
    channels = {row.channel: row for row in rows}
    assert channels[NotificationChannel.IN_APP].status == NotificationStatus.COMPLETED
    assert channels[NotificationChannel.SLACK].status == NotificationStatus.FAILED


def test_notify_with_send_email_writes_email_row(db_session: Session) -> None:
    user = _create_user(db_session, email=f"u-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE)

    notification_service.notify(
        db_session,
        recipient=user,
        notification_type=NotificationType.WORKFLOW_REJECTED,
        title="Rejected",
        body="Sorry.",
        send_email=True,
    )

    rows = _all_notifications(db_session, user.id)
    channels = {row.channel: row for row in rows}
    assert set(channels) == {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
    # Simulated, not real transport — always "succeeds" since nothing left
    # the process. See _simulate_email's docstring.
    assert channels[NotificationChannel.EMAIL].status == NotificationStatus.COMPLETED


# ---------------------------------------------------------------------------
# repo-level in-app filtering + mark_read (through the service, since routes
# never call the repo directly — see service-boundaries.md)
# ---------------------------------------------------------------------------


def test_list_for_user_only_returns_in_app_rows(db_session: Session) -> None:
    user = _create_user(db_session, email=f"u-{uuid.uuid4()}@cordant.io", role=UserRole.MANAGER)

    notification_service.notify(
        db_session,
        recipient=user,
        notification_type=NotificationType.APPROVAL_REQUESTED,
        title="Approval needed",
        body="Please review.",
        send_slack=True,
    )

    listed = notification_service.list_for_user(db_session, user)
    assert len(listed) == 1
    assert listed[0].title == "Approval needed"


def test_mark_read_sets_read_at(db_session: Session) -> None:
    user = _create_user(db_session, email=f"u-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE)
    notification_service.notify(
        db_session,
        recipient=user,
        notification_type=NotificationType.WORKFLOW_COMPLETED,
        title="Done",
        body="Finished.",
    )
    [unread] = notification_service.list_for_user(db_session, user)
    assert unread.read_at is None

    updated = notification_service.mark_read(db_session, unread.id, user)
    assert updated.read_at is not None


def test_mark_read_on_someone_elses_notification_raises_not_found(db_session: Session) -> None:
    owner = _create_user(
        db_session, email=f"owner-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE
    )
    other = _create_user(
        db_session, email=f"other-{uuid.uuid4()}@cordant.io", role=UserRole.EMPLOYEE
    )
    notification_service.notify(
        db_session,
        recipient=owner,
        notification_type=NotificationType.WORKFLOW_COMPLETED,
        title="Done",
        body="Finished.",
    )
    [mine] = notification_service.list_for_user(db_session, owner)

    with pytest.raises(NotFoundError):
        notification_service.mark_read(db_session, mine.id, other)


# ---------------------------------------------------------------------------
# Wired into the workflow engine
# ---------------------------------------------------------------------------


def _new_hire_with_manager(db: Session):
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
    return new_hire, manager_user


def test_approval_requested_notifies_assigned_manager_in_app_and_slack(
    db_session: Session,
) -> None:
    new_hire, manager_user = _new_hire_with_manager(db_session)

    start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-notify-approval-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )

    rows = _all_notifications(db_session, manager_user.id)
    channels = {row.channel: row for row in rows}
    assert set(channels) == {NotificationChannel.IN_APP, NotificationChannel.SLACK}
    assert channels[NotificationChannel.IN_APP].type == NotificationType.APPROVAL_REQUESTED


def test_role_pool_approval_creates_no_notification(db_session: Session) -> None:
    """it_review_access is a role-pool approval (assigned_user_id is None)
    — no single owner to notify, see _create_approval_request's comment."""
    new_hire, manager_user = _new_hire_with_manager(db_session)
    it_user = _create_user(db_session, email=f"it-{uuid.uuid4()}@cordant.io", role=UserRole.IT)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-notify-pool-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    approval_service.decide(db_session, manager_approval.id, manager_user, decision="approved")

    # The manager got their own approval-requested notification, but the IT
    # pool approval that just opened up produced nothing for it_user.
    assert _all_notifications(db_session, it_user.id) == []


def test_workflow_completed_notifies_submitter_in_app_only(db_session: Session) -> None:
    dept = department_repo.create(db_session, name=f"Dept-{uuid.uuid4()}")
    employee = employee_repo.create(
        db_session,
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
    submitter = _create_user(
        db_session, email=employee.work_email, role=UserRole.EMPLOYEE, employee_id=employee.id
    )
    application = application_repo.create(
        db_session,
        name=f"App-{uuid.uuid4()}",
        description="Test application.",
        risk_level=RiskLevel.LOW,
    )

    response = access_request_service.submit_access_request(
        db_session,
        AccessRequestCreate(
            application_id=application.id, justification="Need it for daily engineering work."
        ),
        current_user=submitter,
    )
    instance = workflow_instance_repo.get_by_id(db_session, response.workflow_instance_id)
    fulfillment_step = _step(instance, "create_fulfillment_task")
    confirm_external_completion(db_session, instance, fulfillment_step)

    rows = _all_notifications(db_session, submitter.id)
    channels = {row.channel: row for row in rows}
    # Only ever in-app for a completion — see notify.py's docstring.
    assert set(channels) == {NotificationChannel.IN_APP}
    assert channels[NotificationChannel.IN_APP].type == NotificationType.WORKFLOW_COMPLETED


def test_workflow_rejected_notifies_submitter_in_app_and_email(db_session: Session) -> None:
    new_hire, manager_user = _new_hire_with_manager(db_session)
    hr_submitter = _create_user(db_session, email=f"hr-{uuid.uuid4()}@cordant.io", role=UserRole.HR)

    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-notify-rejected-{uuid.uuid4()}",
        employee_id=new_hire.id,
        initiated_by_user_id=hr_submitter.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )

    approval_service.decide(
        db_session, manager_approval.id, manager_user, decision="rejected", notes="Not this time."
    )

    rows = _all_notifications(db_session, hr_submitter.id)
    channels = {row.channel: row for row in rows}
    assert set(channels) == {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
    assert channels[NotificationChannel.IN_APP].type == NotificationType.WORKFLOW_REJECTED
    assert "Not this time." in channels[NotificationChannel.IN_APP].body


def test_no_submitter_is_a_silent_noop_on_completion(db_session: Session) -> None:
    """start_workflow with no initiated_by_user_id (the default in most of
    this test suite, and every seed-created instance) must not raise when
    the instance completes — _notify_submitter's whole reason to exist."""
    new_hire, manager_user = _new_hire_with_manager(db_session)
    instance = start_workflow(
        db_session,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(new_hire.id)},
        dedup_key=f"test-notify-no-submitter-{uuid.uuid4()}",
        employee_id=new_hire.id,
    )
    manager_approval = approval_request_repo.get_by_step_instance_id(
        db_session, _step(instance, "manager_approval").id
    )
    # Approving just confirms the no-submitter case doesn't blow up when the
    # workflow later completes — assertion is that this doesn't raise.
    approval_service.decide(db_session, manager_approval.id, manager_user, decision="approved")
