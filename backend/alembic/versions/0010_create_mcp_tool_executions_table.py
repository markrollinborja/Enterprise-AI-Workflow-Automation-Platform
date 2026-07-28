"""create mcp_tool_executions table

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-28 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MCP_TOOL_CALLER_ENUM = postgresql.ENUM(
    "workflow_engine", "ai_agent",
    name="mcp_tool_caller",
    create_type=False,
)
MCP_EXECUTION_STATUS_ENUM = postgresql.ENUM(
    "completed", "failed",
    name="mcp_execution_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    MCP_TOOL_CALLER_ENUM.create(bind, checkfirst=True)
    MCP_EXECUTION_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "mcp_tool_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("caller", MCP_TOOL_CALLER_ENUM, nullable=False),
        sa.Column(
            "workflow_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_instances.id"),
            nullable=True,
        ),
        sa.Column(
            "step_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_step_instances.id"),
            nullable=True,
        ),
        sa.Column("input_params", postgresql.JSONB(), nullable=False),
        sa.Column("output_result", postgresql.JSONB(), nullable=True),
        sa.Column("status", MCP_EXECUTION_STATUS_ENUM, nullable=False),
        sa.Column("mock_mode", sa.Boolean(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_mcp_tool_executions_tool_name", "mcp_tool_executions", ["tool_name"])
    op.create_index(
        "ix_mcp_tool_executions_workflow_instance_id",
        "mcp_tool_executions",
        ["workflow_instance_id"],
    )
    op.create_index(
        "ix_mcp_tool_executions_step_instance_id", "mcp_tool_executions", ["step_instance_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_tool_executions_step_instance_id", table_name="mcp_tool_executions")
    op.drop_index(
        "ix_mcp_tool_executions_workflow_instance_id", table_name="mcp_tool_executions"
    )
    op.drop_index("ix_mcp_tool_executions_tool_name", table_name="mcp_tool_executions")
    op.drop_table("mcp_tool_executions")
    MCP_EXECUTION_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    MCP_TOOL_CALLER_ENUM.drop(op.get_bind(), checkfirst=True)
