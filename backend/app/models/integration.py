"""Integration connection management (V2 Module 1).

Two tables, and the split between them is the whole design.

`IntegrationConnection` is *current state* — one row per provider
connection, mutated in place. It answers "is Salesforce working right now?"
in a single indexed read, which is what the support console's health grid
and the Grafana integration dashboard both need.

`HealthCheckResult` is *history* — one immutable row per check. It answers
"when did Salesforce start failing, and what did it say?", which is the
question during an incident, and it is the series behind uptime and
mean-time-to-recover. Overwriting a single status column would make the
first question answerable and the second impossible.

**No secrets live here.** The connection stores a `credential_ref` — the
name of the environment variable holding the credential — never the
credential. See ADR-0016 for why a portfolio project deliberately stops at
environment-variable indirection rather than pretending to have a KMS, and
what a real deployment would need instead.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import (
    ConnectionStatus,
    HealthStatus,
    ProviderAuthMethod,
    ProviderMode,
    ProviderType,
    enum_values,
)


class IntegrationConnection(Base):
    """One configured connection to one external system."""

    __tablename__ = "integration_connections"
    __table_args__ = (
        # One connection per (provider, key) rather than per provider alone:
        # a single platform legitimately holds two Salesforce connections
        # (sandbox and production) or two SCIM clients (one per customer
        # organization). Keying on provider alone would model that as a
        # conflict rather than the normal case it is.
        UniqueConstraint("provider", "connection_key", name="uq_connection_provider_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[ProviderType] = mapped_column(
        SAEnum(ProviderType, name="provider_type", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    # Stable, human-typed identifier used in config, seeds, and URLs
    # ("salesforce-dev", "scim-cordant"). Not the display name: display
    # names get edited, and anything that appears in a URL or a seed script
    # must not change underneath.
    connection_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Nullable because platform-wide connections (Jira, Slack) are not
    # scoped to a customer, while SCIM clients and Salesforce org syncs
    # are. Kept as free text in Phase 1 — the Organization table arrives in
    # Phase 2 with Salesforce, and this becomes a foreign key then rather
    # than inventing an entity before anything populates it.
    organization_ref: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    status: Mapped[ConnectionStatus] = mapped_column(
        SAEnum(ConnectionStatus, name="connection_status", values_callable=enum_values),
        nullable=False,
        default=ConnectionStatus.ENABLED,
    )
    mode: Mapped[ProviderMode] = mapped_column(
        SAEnum(ProviderMode, name="provider_mode", values_callable=enum_values),
        nullable=False,
        default=ProviderMode.SIMULATED,
    )
    auth_method: Mapped[ProviderAuthMethod] = mapped_column(
        SAEnum(ProviderAuthMethod, name="provider_auth_method", values_callable=enum_values),
        nullable=False,
        default=ProviderAuthMethod.NONE,
    )

    # The *name of the environment variable* holding this connection's
    # credential — e.g. "SALESFORCE_CLIENT_SECRET". Never the value. A
    # database dump of this table is therefore safe to attach to a bug
    # report, which is not true of any design that encrypts secrets into
    # the row and keeps the key nearby.
    credential_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Non-secret provider settings: API version, instance URL, SCIM schema
    # URN, tenant ID. Anything secret belongs behind credential_ref, and
    # the service layer redacts this on write as a second line of defence
    # rather than trusting every future caller to have read this comment.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Bumped on every configuration change, so a health result or a failed
    # call can be attributed to the configuration that was live at the
    # time. Without it, "it started failing after someone changed
    # something" is unprovable.
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    health_status: Mapped[HealthStatus] = mapped_column(
        SAEnum(HealthStatus, name="health_status", values_callable=enum_values),
        nullable=False,
        default=HealthStatus.UNKNOWN,
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Redacted at construction of the ProviderError that produced it, and
    # length-bounded there too — see app/core/provider_errors.py.
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reset to zero on any success. Drives escalation ("this has failed 12
    # times in a row") without requiring an aggregate query over history on
    # every dashboard render.
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Populated only for OAuth connections that issue expiring tokens. Its
    # value is a timestamp, never the token — this is what powers the
    # "token expiring in under 24h" warning on the integration dashboard,
    # which is a far more useful signal than discovering expiry at 3am when
    # a workflow fails.
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    health_checks: Mapped[list["HealthCheckResult"]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
    )

    @property
    def is_usable(self) -> bool:
        """Whether the platform should attempt a call on this connection.

        Deliberately does not consider `health_status`: an UNHEALTHY
        connection must still be *attempted*, because a health check is a
        lagging indicator and refusing to try guarantees it can never
        recover on its own. Only the operator's explicit DISABLED is a
        reason not to call.
        """
        return self.status is ConnectionStatus.ENABLED


class HealthCheckResult(Base):
    """One immutable record of one health check.

    Append-only. Nothing updates a row here — that is what makes it usable
    as an incident timeline and as the series behind uptime and MTTR
    metrics (Module 7).
    """

    __tablename__ = "health_check_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("integration_connections.id"), nullable=False, index=True
    )
    status: Mapped[HealthStatus] = mapped_column(
        SAEnum(HealthStatus, name="health_status", values_callable=enum_values), nullable=False
    )
    # Separate from `status` because a check can be DEGRADED while
    # succeeding, and UNHEALTHY while the request technically returned. The
    # boolean is "did the call complete"; the status is "what does that
    # mean for the operator".
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Redacted upstream — see provider_errors.summarize().
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which classification the failure got (TransientProviderError,
    # ProviderAuthError, ...). Stored as text rather than an enum because
    # the taxonomy will grow with each provider added in Phases 2-6, and an
    # enum column would demand a migration for every addition to what is
    # fundamentally a diagnostic label.
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Which run this check belonged to. A scheduled sweep across every
    # provider (Module 3's health-check workflow) shares one ID, so the
    # support console can show "the 04:00 sweep" as a single event rather
    # than eight unrelated rows.
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # The configuration in force when this check ran — see
    # IntegrationConnection.config_version.
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    connection: Mapped["IntegrationConnection"] = relationship(back_populates="health_checks")
