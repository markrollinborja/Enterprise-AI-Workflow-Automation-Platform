"""Customer organizations and their identities in external systems.

V1's domain was internal: employees, departments, access packages. V2 adds a
second subject — the customer organization onboarded when a Salesforce
opportunity closes. The workflow engine does not care which it is, and that
is the point of the platform: approval-gated onboarding is the same process
whether the subject is a new hire or a new customer.

`ExternalIdentity` is deliberately generic rather than a `salesforce_id`
column on Organization. The same organization will shortly also exist as a
Keycloak group (Phase 3), a SCIM resource (Phase 5), and a Microsoft Graph
group (Phase 4). A column per system means a migration per system and a
schema that advertises which integrations were built first; one mapping
table means each new system is rows, not DDL.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import (
    ExternalEntityType,
    OrganizationStatus,
    ProviderType,
    enum_values,
)


class Organization(Base):
    """A customer organization."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Stable, URL-safe key derived from the name at creation and never
    # changed afterwards. Names get corrected ("Cordant Inc" -> "Cordant
    # Industries, Inc.") and anything that appears in a URL, a Slack
    # message, or a Jira ticket must survive that.
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[OrganizationStatus] = mapped_column(
        SAEnum(OrganizationStatus, name="organization_status", values_callable=enum_values),
        nullable=False,
        default=OrganizationStatus.PROSPECTIVE,
    )
    # Used later to route a user to the right organization at login (Phase
    # 3) and to scope SCIM provisioning (Phase 5). Nullable because a
    # Salesforce Account frequently has no website recorded, and refusing
    # to sync an account over a missing optional field would be the
    # integration failing for a reason the business does not care about.
    primary_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # No ORM relationship to ExternalIdentity on purpose. The join would
    # have to be a hand-written primaryjoin filtered on entity_type,
    # because entity_id is polymorphic (see ExternalIdentity's docstring) —
    # a construct that is easy to get subtly wrong, hard to read, and
    # produces confusing lazy-load behavior. Callers go through
    # repositories/external_identity_repo.py, which is explicit about which
    # entity type it is asking for.


class ExternalIdentity(Base):
    """Maps one local record to its identity in one external system.

    `entity_id` is intentionally *not* a foreign key. It points at a
    different table depending on `entity_type` (organizations, users,
    employees), which SQL foreign keys cannot express without either a
    nullable column per target table or a separate mapping table per
    entity type. Both alternatives were rejected as more schema for no more
    safety: the integrity that matters here — one external ID maps to at
    most one local record — is enforced by the unique constraint below,
    and orphan rows are harmless because every read path starts from the
    local record.
    """

    __tablename__ = "external_identities"
    __table_args__ = (
        # The idempotency guarantee for every sync in the platform. Seeing
        # Salesforce Account 001xx000003DGb2AAG twice must find the
        # existing organization, not create a second one — and enforcing
        # that in Postgres rather than in a service means a concurrent
        # double-delivery loses the race instead of duplicating the row.
        UniqueConstraint(
            "system", "entity_type", "external_id", name="uq_external_identity_system_entity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    system: Mapped[ProviderType] = mapped_column(
        SAEnum(ProviderType, name="provider_type", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[ExternalEntityType] = mapped_column(
        SAEnum(ExternalEntityType, name="external_entity_type", values_callable=enum_values),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Deep link into the provider's UI, when one can be constructed. Purely
    # for the support console: "open this account in Salesforce" saves a
    # support engineer a search, and a stored URL is more reliable than
    # rebuilding one from an ID and an instance URL at render time.
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Which connection produced this mapping. Two Salesforce connections
    # (sandbox and production) legitimately map the same organization to
    # two different Account IDs, and without this the second sync would
    # look like data corruption rather than the normal case it is.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("integration_connections.id"), nullable=True, index=True
    )
