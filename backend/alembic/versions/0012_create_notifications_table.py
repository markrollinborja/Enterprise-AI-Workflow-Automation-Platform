"""create notifications table

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-28 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_TYPE_ENUM = postgresql.ENUM(
    "approval_requested", "workflow_completed", "workflow_rejected",
    name="notification_type",
    create_type=False,
)
NOTIFICATION_CHANNEL_ENUM = postgresql.ENUM(
    "in_app", "slack", "email",
    name="notification_channel",
    create_type=False,
)
NOTIFICATION_STATUS_ENUM = postgresql.ENUM(
    "completed", "failed",
    name="notification_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    NOTIFICATION_TYPE_ENUM.create(bind, checkfirst=True)
    NOTIFICATION_CHANNEL_ENUM.create(bind, checkfirst=True)
    NOTIFICATION_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workflow_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_instances.id"),
            nullable=True,
        ),
        sa.Column("type", NOTIFICATION_TYPE_ENUM, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("channel", NOTIFICATION_CHANNEL_ENUM, nullable=False),
        sa.Column("status", NOTIFICATION_STATUS_ENUM, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index(
        "ix_notifications_workflow_instance_id", "notifications", ["workflow_instance_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_workflow_instance_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    NOTIFICATION_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    NOTIFICATION_CHANNEL_ENUM.drop(op.get_bind(), checkfirst=True)
    NOTIFICATION_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
