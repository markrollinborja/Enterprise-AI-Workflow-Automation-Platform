from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import NotificationChannel
from app.models.notification import Notification


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
