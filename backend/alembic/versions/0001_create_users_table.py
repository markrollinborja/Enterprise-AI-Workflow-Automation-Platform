"""create users table

Revision ID: 0001
Revises:
Create Date: 2026-07-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE_ENUM = sa.Enum(
    "employee", "manager", "hr", "it", "security", "administrator",
    name="user_role",
)


def upgrade() -> None:
    # Don't call USER_ROLE_ENUM.create(...) here — op.create_table() below
    # already creates any Enum type referenced by its columns as part of the
    # table DDL. Creating it twice (once manually, once automatically) makes
    # the second attempt fail with "type already exists" even with
    # checkfirst=True, because that flag isn't honored on the automatic path.
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", USER_ROLE_ENUM, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    USER_ROLE_ENUM.drop(op.get_bind(), checkfirst=True)
