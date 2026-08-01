from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.enums import NotificationChannel, NotificationType
from app.models.notification import Notification
from app.models.workflow import WorkflowInstance


def get_by_id(db: Session, notification_id: UUID) -> Notification | None:
    return db.get(Notification, notification_id)


def create(db: Session, **fields: Any) -> Notification:
    notification = Notification(**fields)
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def list_for_user(db: Session, user_id: UUID) -> list[Notification]:
    """IN_APP rows are the only ones a user would ever see in their own
    list — SLACK/EMAIL rows exist purely as delivery-attempt records for
    the audit trail (Principle 4), not something a user reads back through
    this app. See services/notifications/service.py's docstring."""
    return list(
        db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.channel == NotificationChannel.IN_APP,
            )
            .order_by(Notification.created_at.desc())
        )
    )


def mark_read(db: Session, notification: Notification) -> Notification:
    notification.read_at = datetime.now(UTC)
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def mark_approval_requested_read(db: Session, *, user_id: UUID, workflow_instance_id: UUID) -> None:
    """Called from services/approvals/service.py::decide() the moment a
    user acts on an approval — without this, the "Approval needed" in-app
    notification that put it in their queue stays unread forever unless
    they separately click "Mark read" on it, which is a confusing double
    action (see the bug this fixed: an approver would approve a request and
    still see "1 unread" for the thing they just handled). Matches on
    user_id + workflow_instance_id + APPROVAL_REQUESTED rather than a
    precise step_instance_id FK (Notification doesn't have one — see the
    model's docstring on why it only links to workflow_instance_id) — safe
    in practice since a single workflow instance only ever asks the same
    user for one pending approval_requested notification at a time."""
    notifications = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.workflow_instance_id == workflow_instance_id,
            Notification.type == NotificationType.APPROVAL_REQUESTED,
            Notification.channel == NotificationChannel.IN_APP,
            Notification.read_at.is_(None),
        )
    ).all()
    now = datetime.now(UTC)
    for notification in notifications:
        notification.read_at = now
        db.add(notification)
    if notifications:
        db.commit()


def list_for_timeline(
    db: Session, *, workflow_instance_id: UUID | None = None, limit: int = 100
) -> list[Notification]:
    """Unlike list_for_user (IN_APP only, what a recipient's inbox shows),
    this returns every channel — the Phase 12 composed audit timeline's
    "notification sent" entries need the SLACK/EMAIL delivery attempts too,
    not just the in-app row. See services/dashboard/service.py."""
    query = select(Notification).options(
        joinedload(Notification.user),
        joinedload(Notification.workflow_instance).joinedload(WorkflowInstance.workflow_definition),
    )
    if workflow_instance_id is not None:
        query = query.where(Notification.workflow_instance_id == workflow_instance_id).order_by(
            Notification.created_at
        )
    else:
        query = query.order_by(Notification.created_at.desc()).limit(limit)
    return list(db.scalars(query))
