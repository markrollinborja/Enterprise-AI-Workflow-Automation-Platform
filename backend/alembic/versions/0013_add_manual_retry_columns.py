"""add manual retry columns to workflow_step_instances

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Phase 13b: who manually retried a FAILED step, and when — distinct
    # from attempt_count (which already tracks *how many times*, automatic
    # backoff retries included) and from error_message (which only ever
    # reflects the *last* attempt's outcome). Both nullable: every existing
    # row, and every step that's never failed or was only ever retried
    # automatically, leaves these unset.
    op.add_column(
        "workflow_step_instances",
        sa.Column(
            "retried_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True
        ),
    )
    op.add_column(
        "workflow_step_instances",
        sa.Column("retried_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_step_instances", "retried_at")
    op.drop_column("workflow_step_instances", "retried_by_user_id")
