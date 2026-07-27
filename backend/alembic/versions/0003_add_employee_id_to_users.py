"""add employee_id to users

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26 00:00:00.000001

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("employee_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_employee_id_employees", "users", "employees", ["employee_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_employee_id_employees", "users", type_="foreignkey")
    op.drop_column("users", "employee_id")
