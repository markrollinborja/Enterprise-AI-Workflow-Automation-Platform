"""add external_ref column and waiting_external step status

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-28 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres enums can't have a value added and used in the same
    # transaction pre-PG12, but this migration only adds the value — it's
    # never referenced in this same upgrade() — so running it inside
    # alembic's normal per-migration transaction is safe on PG16.
    op.execute("ALTER TYPE step_status ADD VALUE IF NOT EXISTS 'waiting_external'")

    # Stores the Jira issue key for a mcp_tool step flagged
    # awaits_fulfillment (see StepDefinition, ADR-0010) — what the
    # /webhooks/jira route looks a step up by. Not unique: mock mode's
    # fake issue keys aren't guaranteed globally unique (see
    # mcp_server/app/tools/jira.py), only real Jira Cloud keys are: an
    # index is enough to make the webhook's lookup fast without a
    # constraint mock mode can't honor.
    op.add_column(
        "workflow_step_instances", sa.Column("external_ref", sa.String(length=100), nullable=True)
    )
    op.create_index(
        "ix_workflow_step_instances_external_ref",
        "workflow_step_instances",
        ["external_ref"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_step_instances_external_ref", table_name="workflow_step_instances"
    )
    op.drop_column("workflow_step_instances", "external_ref")
    # Postgres has no ALTER TYPE ... DROP VALUE — removing an enum value
    # safely requires rebuilding the type (rename, create new, migrate
    # column, drop old), real work for a downgrade path this project's
    # tests don't exercise. Left as a no-op, documented rather than silently
    # incomplete: downgrading past this migration leaves 'waiting_external'
    # as a valid (if unused) step_status value.
