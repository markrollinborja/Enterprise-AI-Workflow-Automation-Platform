"""create applications table

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-27 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# risk_level already exists — created in migration 0002 for
# employees.risk_level. Referenced here with create_type=False, never
# created again (and never dropped in this migration's downgrade() either —
# employees.risk_level still depends on it after applications is gone). See
# migration 0006's comment for the full reasoning on why postgresql.ENUM +
# create_type=False is the pattern for every reused enum type.
RISK_LEVEL_ENUM = postgresql.ENUM(
    "low", "medium", "high",
    name="risk_level",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk_level", RISK_LEVEL_ENUM, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_applications_name", "applications", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_applications_name", table_name="applications")
    op.drop_table("applications")
