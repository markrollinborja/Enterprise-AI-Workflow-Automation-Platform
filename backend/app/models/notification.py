"""One row per (event, channel) pair — see NotificationChannel's docstring
for why an APPROVAL_REQUESTED event that fires both in-app and Slack writes
two rows, not one row with a list of channels. Reserved in Phase 1's
original data-model sketch, built for real in Phase 11 — see
docs/architecture/service-boundaries.md's "notifications" section.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import NotificationChannel, NotificationStatus, NotificationType, enum_values

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workflow import WorkflowInstance


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The recipient. Always a real User — see services/notifications/service.py:
    # a trigger with no linked user (e.g. an onboarding instance whose new
    # hire has no login yet) is a no-op, never a row with a null recipient.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True
    )
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=True, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, name="notification_type", values_callable=enum_values),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", values_callable=enum_values),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Only ever set on IN_APP rows — "read" is a recipient-facing concept
    # for something they'd see in a notification list; a SLACK/EMAIL row's
    # delivery outcome is fully captured by `status` instead.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship()
    workflow_instance: Mapped["WorkflowInstance | None"] = relationship()
