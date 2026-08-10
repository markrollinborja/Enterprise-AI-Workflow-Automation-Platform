"""create integration_connections and health_check_results

V2 Module 1 — see app/models/integration.py for why current state and check
history are two tables rather than one, and ADR-0016 for why no secret is
stored in either.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-10 16:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVIDER_TYPE_ENUM = postgresql.ENUM(
    "salesforce",
    "n8n",
    "keycloak",
    "microsoft_graph",
    "jira",
    "slack",
    "google_calendar",
    "scim_client",
    name="provider_type",
    create_type=False,
)
PROVIDER_MODE_ENUM = postgresql.ENUM(
    "live",
    "simulated",
    name="provider_mode",
    create_type=False,
)
PROVIDER_AUTH_METHOD_ENUM = postgresql.ENUM(
    "oauth2_client_credentials",
    "oauth2_authorization_code",
    "oauth2_jwt_bearer",
    "api_token",
    "basic",
    "service_account",
    "none",
    name="provider_auth_method",
    create_type=False,
)
CONNECTION_STATUS_ENUM = postgresql.ENUM(
    "enabled",
    "disabled",
    name="connection_status",
    create_type=False,
)
HEALTH_STATUS_ENUM = postgresql.ENUM(
    "unknown",
    "healthy",
    "degraded",
    "unhealthy",
    name="health_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    PROVIDER_TYPE_ENUM.create(bind, checkfirst=True)
    PROVIDER_MODE_ENUM.create(bind, checkfirst=True)
    PROVIDER_AUTH_METHOD_ENUM.create(bind, checkfirst=True)
    CONNECTION_STATUS_ENUM.create(bind, checkfirst=True)
    HEALTH_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", PROVIDER_TYPE_ENUM, nullable=False),
        sa.Column("connection_key", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("organization_ref", sa.String(length=200), nullable=True),
        sa.Column("status", CONNECTION_STATUS_ENUM, nullable=False),
        sa.Column("mode", PROVIDER_MODE_ENUM, nullable=False),
        sa.Column("auth_method", PROVIDER_AUTH_METHOD_ENUM, nullable=False),
        # Holds the *name* of an environment variable, never a credential.
        sa.Column("credential_ref", sa.String(length=200), nullable=True),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("health_status", HEALTH_STATUS_ENUM, nullable=False),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failure_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Enforced in the database, not only in the model: a sandbox and a
        # production Salesforce connection are both legitimate, two rows
        # claiming to be the same one are not.
        sa.UniqueConstraint("provider", "connection_key", name="uq_connection_provider_key"),
    )
    op.create_index("ix_integration_connections_provider", "integration_connections", ["provider"])
    op.create_index(
        "ix_integration_connections_organization_ref",
        "integration_connections",
        ["organization_ref"],
    )

    op.create_table(
        "health_check_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("integration_connections.id"),
            nullable=False,
        ),
        sa.Column("status", HEALTH_STATUS_ENUM, nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_health_check_results_connection_id", "health_check_results", ["connection_id"]
    )
    # The support console's primary lookup is by correlation ID, and the
    # integration dashboard's is by time — both get their own index rather
    # than relying on a scan of what becomes the largest table in this
    # module.
    op.create_index(
        "ix_health_check_results_correlation_id", "health_check_results", ["correlation_id"]
    )
    op.create_index("ix_health_check_results_checked_at", "health_check_results", ["checked_at"])


def downgrade() -> None:
    op.drop_index("ix_health_check_results_checked_at", table_name="health_check_results")
    op.drop_index("ix_health_check_results_correlation_id", table_name="health_check_results")
    op.drop_index("ix_health_check_results_connection_id", table_name="health_check_results")
    op.drop_table("health_check_results")

    op.drop_index(
        "ix_integration_connections_organization_ref", table_name="integration_connections"
    )
    op.drop_index("ix_integration_connections_provider", table_name="integration_connections")
    op.drop_table("integration_connections")

    bind = op.get_bind()
    HEALTH_STATUS_ENUM.drop(bind, checkfirst=True)
    CONNECTION_STATUS_ENUM.drop(bind, checkfirst=True)
    PROVIDER_AUTH_METHOD_ENUM.drop(bind, checkfirst=True)
    PROVIDER_MODE_ENUM.drop(bind, checkfirst=True)
    PROVIDER_TYPE_ENUM.drop(bind, checkfirst=True)
