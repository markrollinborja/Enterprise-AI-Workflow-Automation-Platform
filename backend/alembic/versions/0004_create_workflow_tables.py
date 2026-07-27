"""create workflow_definitions, workflow_instances, workflow_step_instances

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER_TYPE_ENUM = sa.Enum("event", "manual", name="trigger_type")
INSTANCE_STATUS_ENUM = sa.Enum(
    "pending",
    "running",
    "waiting_approval",
    "waiting_external",
    "completed",
    "failed",
    "rejected",
    "cancelled",
    name="instance_status",
)
STEP_STATUS_ENUM = sa.Enum(
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "skipped",
    "rejected",
    name="step_status",
)
STEP_TYPE_ENUM = sa.Enum("validation", "approval", "ai_action", "mcp_tool", name="step_type")


def upgrade() -> None:
    # As in migration 0002: op.create_table() creates the Enum types it
    # references automatically — no manual .create() calls here.
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("trigger_type", TRIGGER_TYPE_ENUM, nullable=False),
        sa.Column("trigger_event", sa.String(length=100), nullable=True),
        sa.Column("definition_json", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_workflow_definitions_key", "workflow_definitions", ["key"])

    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workflow_definition_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_definitions.id"),
            nullable=False,
        ),
        sa.Column("status", INSTANCE_STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("input_data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "initiated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("current_step_key", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_workflow_instances_status", "workflow_instances", ["status"]
    )

    op.create_table(
        "workflow_step_instances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workflow_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_instances.id"),
            nullable=False,
        ),
        sa.Column("step_key", sa.String(length=100), nullable=False),
        sa.Column("step_type", STEP_TYPE_ENUM, nullable=False),
        sa.Column("status", STEP_STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("input_data", postgresql.JSONB(), nullable=True),
        sa.Column("output_data", postgresql.JSONB(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_workflow_step_instances_workflow_instance_id",
        "workflow_step_instances",
        ["workflow_instance_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_step_instances_workflow_instance_id",
        table_name="workflow_step_instances",
    )
    op.drop_table("workflow_step_instances")
    op.drop_index("ix_workflow_instances_status", table_name="workflow_instances")
    op.drop_table("workflow_instances")
    op.drop_index("ix_workflow_definitions_key", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
    STEP_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
    STEP_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    INSTANCE_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    TRIGGER_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
