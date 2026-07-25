"""create departments and employees tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPLOYMENT_TYPE_ENUM = sa.Enum(
    "full_time", "part_time", "contractor",
    name="employment_type",
)
EMPLOYEE_STATUS_ENUM = sa.Enum(
    "active", "pending", "on_leave", "terminated",
    name="employee_status",
)
RISK_LEVEL_ENUM = sa.Enum(
    "low", "medium", "high",
    name="risk_level",
)


def upgrade() -> None:
    # No manual .create() calls for the enum types below — op.create_table()
    # creates any Enum type referenced by its columns automatically. Calling
    # .create() separately first is what caused the "type already exists"
    # bug in migration 0001; not repeating it here.
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_departments_name", "departments", ["name"], unique=True)

    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("work_email", sa.String(length=255), nullable=False),
        sa.Column("personal_email", sa.String(length=255), nullable=True),
        sa.Column("job_title", sa.String(length=255), nullable=False),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("manager_id", sa.Uuid(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("employment_type", EMPLOYMENT_TYPE_ENUM, nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", EMPLOYEE_STATUS_ENUM, nullable=False, server_default="active"),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("risk_level", RISK_LEVEL_ENUM, nullable=False, server_default="low"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_employees_work_email", "employees", ["work_email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_employees_work_email", table_name="employees")
    op.drop_table("employees")
    op.drop_index("ix_departments_name", table_name="departments")
    op.drop_table("departments")
    RISK_LEVEL_ENUM.drop(op.get_bind(), checkfirst=True)
    EMPLOYEE_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
    EMPLOYMENT_TYPE_ENUM.drop(op.get_bind(), checkfirst=True)
