"""create access_packages table

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# risk_level already exists (migration 0002) — referenced here, never
# created or dropped in this migration (employees.risk_level and
# applications.risk_level both still depend on it).
RISK_LEVEL_ENUM = postgresql.ENUM(
    "low", "medium", "high",
    name="risk_level",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "access_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("risk_level", RISK_LEVEL_ENUM, nullable=False),
        sa.Column("included_systems", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_access_packages_name", "access_packages", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_access_packages_name", table_name="access_packages")
    op.drop_table("access_packages")
