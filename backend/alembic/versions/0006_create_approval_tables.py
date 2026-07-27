"""create approval_requests, approval_decisions

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Both enum types below are declared create_type=False and never created via
# op.create_table()'s automatic type-creation dispatch — that mechanism turned
# out to be unreliable in practice: when a create_type=False column and a
# create_type=True column land in the *same* create_table() call, Postgres's
# enum-creation event can still fire for the create_type=False one and blow up
# with "type already exists" (this bit us live against a real Postgres
# instance — see git history for the traceback). Instead we create each type
# explicitly, once, with checkfirst=True (idempotent — safe whether or not it
# already exists), then reference it everywhere as create_type=False. Using
# postgresql.ENUM (the dialect-specific class) rather than generic sa.Enum is
# the pattern Alembic's own cookbook recommends for exactly this situation.

# Already exists — created in migration 0001. Never created here.
USER_ROLE_ENUM = postgresql.ENUM(
    "employee", "manager", "hr", "it", "security", "administrator",
    name="user_role",
    create_type=False,
)

# New in this migration — referenced by both approval_requests.status and
# approval_decisions.decision (see app/models/approval.py). Created explicitly
# below, once, before either table exists.
APPROVAL_REQUEST_STATUS_ENUM = postgresql.ENUM(
    "pending", "approved", "rejected",
    name="approval_request_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    APPROVAL_REQUEST_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "approval_requests",
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
        sa.Column("approver_role", USER_ROLE_ENUM, nullable=False),
        sa.Column("assigned_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "status", APPROVAL_REQUEST_STATUS_ENUM, nullable=False, server_default="pending"
        ),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_approval_requests_workflow_instance_id",
        "approval_requests",
        ["workflow_instance_id"],
    )
    op.create_index(
        "ix_approval_requests_step_instance_id", "approval_requests", ["step_instance_id"]
    )
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "approval_request_id",
            sa.Uuid(),
            sa.ForeignKey("approval_requests.id"),
            nullable=False,
        ),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", APPROVAL_REQUEST_STATUS_ENUM, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_approval_decisions_approval_request_id",
        "approval_decisions",
        ["approval_request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_approval_decisions_approval_request_id", table_name="approval_decisions")
    op.drop_table("approval_decisions")
    op.drop_index("ix_approval_requests_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_step_instance_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_workflow_instance_id", table_name="approval_requests")
    op.drop_table("approval_requests")
    APPROVAL_REQUEST_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
