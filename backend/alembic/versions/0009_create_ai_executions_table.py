"""create ai_executions table

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-27 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Both new in this migration — created explicitly, once, before the table
# that references them. See migration 0006's comment for why
# postgresql.ENUM + create_type=False (referenced everywhere else) is the
# pattern.
AI_TASK_TYPE_ENUM = postgresql.ENUM(
    "recommend_access_package", "summarize_justification",
    name="ai_task_type",
    create_type=False,
)
AI_EXECUTION_STATUS_ENUM = postgresql.ENUM(
    "completed", "failed",
    name="ai_execution_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    AI_TASK_TYPE_ENUM.create(bind, checkfirst=True)
    AI_EXECUTION_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "ai_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workflow_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_instances.id"),
            nullable=False,
        ),
        sa.Column(
            "step_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_step_instances.id"),
            nullable=False,
        ),
        sa.Column("task_type", AI_TASK_TYPE_ENUM, nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("output_json", postgresql.JSONB(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("requires_human_review", sa.Boolean(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("status", AI_EXECUTION_STATUS_ENUM, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_ai_executions_workflow_instance_id", "ai_executions", ["workflow_instance_id"]
    )
    op.create_index("ix_ai_executions_step_instance_id", "ai_executions", ["step_instance_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_executions_step_instance_id", table_name="ai_executions")
    op.drop_index("ix_ai_executions_workflow_instance_id", table_name="ai_executions")
    op.drop_table("ai_executions")
    AI_EXECUTION_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    AI_TASK_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
