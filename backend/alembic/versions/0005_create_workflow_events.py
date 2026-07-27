"""create workflow_events

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(length=150), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "workflow_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_instances.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workflow_events_dedup_key", "workflow_events", ["dedup_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_events_dedup_key", table_name="workflow_events")
    op.drop_table("workflow_events")
