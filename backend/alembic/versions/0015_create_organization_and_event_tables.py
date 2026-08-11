"""create organizations, external_identities and inbound_events

V2 Module 2 — see app/models/organization.py for why external identities are
one generic mapping table rather than a column per provider, and
app/models/inbound_event.py for why idempotency is a unique constraint rather
than a service-layer check.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-10 18:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# provider_type already exists from migration 0014 — referenced, never
# recreated. create_type=False on every ENUM in this file for that reason;
# Alembic would otherwise emit a CREATE TYPE that fails on the second
# migration to use the same enum.
PROVIDER_TYPE_ENUM = postgresql.ENUM(name="provider_type", create_type=False)

ORGANIZATION_STATUS_ENUM = postgresql.ENUM(
    "prospective",
    "onboarding",
    "active",
    "suspended",
    name="organization_status",
    create_type=False,
)
EXTERNAL_ENTITY_TYPE_ENUM = postgresql.ENUM(
    "organization",
    "user",
    "employee",
    name="external_entity_type",
    create_type=False,
)
INBOUND_EVENT_STATUS_ENUM = postgresql.ENUM(
    "received",
    "processed",
    "duplicate",
    "failed",
    "rejected",
    name="inbound_event_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    ORGANIZATION_STATUS_ENUM.create(bind, checkfirst=True)
    EXTERNAL_ENTITY_TYPE_ENUM.create(bind, checkfirst=True)
    INBOUND_EVENT_STATUS_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False, unique=True),
        sa.Column("status", ORGANIZATION_STATUS_ENUM, nullable=False),
        sa.Column("primary_domain", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
    op.create_index("ix_organizations_primary_domain", "organizations", ["primary_domain"])

    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("system", PROVIDER_TYPE_ENUM, nullable=False),
        sa.Column("entity_type", EXTERNAL_ENTITY_TYPE_ENUM, nullable=False),
        # No FK: entity_id is polymorphic across organizations/users/
        # employees. The integrity that matters is the unique constraint
        # below — one external ID maps to at most one local record.
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("external_url", sa.String(length=500), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("integration_connections.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "system", "entity_type", "external_id", name="uq_external_identity_system_entity"
        ),
    )
    op.create_index("ix_external_identities_system", "external_identities", ["system"])
    op.create_index("ix_external_identities_entity_id", "external_identities", ["entity_id"])
    op.create_index("ix_external_identities_external_id", "external_identities", ["external_id"])
    op.create_index(
        "ix_external_identities_connection_id", "external_identities", ["connection_id"]
    )

    op.create_table(
        "inbound_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivered_by", PROVIDER_TYPE_ENUM, nullable=False),
        sa.Column("source_system", PROVIDER_TYPE_ENUM, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        # Unique — this single constraint is the platform's duplicate-event
        # protection. Two simultaneous deliveries lose the race here rather
        # than both passing a service-layer check.
        sa.Column("idempotency_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", INBOUND_EVENT_STATUS_ENUM, nullable=False),
        sa.Column(
            "workflow_instance_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_instances.id"),
            nullable=True,
        ),
        sa.Column(
            "duplicate_of_id", sa.Uuid(), sa.ForeignKey("inbound_events.id"), nullable=True
        ),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_inbound_events_source_system", "inbound_events", ["source_system"])
    op.create_index("ix_inbound_events_event_type", "inbound_events", ["event_type"])
    op.create_index("ix_inbound_events_idempotency_key", "inbound_events", ["idempotency_key"])
    op.create_index("ix_inbound_events_correlation_id", "inbound_events", ["correlation_id"])
    op.create_index("ix_inbound_events_status", "inbound_events", ["status"])
    op.create_index(
        "ix_inbound_events_workflow_instance_id", "inbound_events", ["workflow_instance_id"]
    )
    op.create_index("ix_inbound_events_received_at", "inbound_events", ["received_at"])


def downgrade() -> None:
    for index in (
        "ix_inbound_events_received_at",
        "ix_inbound_events_workflow_instance_id",
        "ix_inbound_events_status",
        "ix_inbound_events_correlation_id",
        "ix_inbound_events_idempotency_key",
        "ix_inbound_events_event_type",
        "ix_inbound_events_source_system",
    ):
        op.drop_index(index, table_name="inbound_events")
    op.drop_table("inbound_events")

    for index in (
        "ix_external_identities_connection_id",
        "ix_external_identities_external_id",
        "ix_external_identities_entity_id",
        "ix_external_identities_system",
    ):
        op.drop_index(index, table_name="external_identities")
    op.drop_table("external_identities")

    op.drop_index("ix_organizations_primary_domain", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")

    bind = op.get_bind()
    INBOUND_EVENT_STATUS_ENUM.drop(bind, checkfirst=True)
    EXTERNAL_ENTITY_TYPE_ENUM.drop(bind, checkfirst=True)
    ORGANIZATION_STATUS_ENUM.drop(bind, checkfirst=True)
    # provider_type is deliberately not dropped — migration 0014 created it
    # and integration_connections still uses it.
