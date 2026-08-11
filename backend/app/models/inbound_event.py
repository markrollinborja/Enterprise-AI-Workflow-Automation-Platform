"""Inbound integration events — the idempotency and evidence table.

Every event that reaches this platform from outside (n8n forwarding a
normalized Salesforce change, and later SCIM and Graph callbacks) lands here
before anything acts on it. Two jobs:

**Idempotency.** `idempotency_key` is unique. A provider that retries a
delivery it never saw acknowledged is behaving correctly — at-least-once is
the guarantee almost every webhook system actually offers — so the second
delivery must be recognised, acknowledged with a 2xx, and not acted on
twice. Enforcing that with a unique constraint rather than a service-layer
"have I seen this?" check means two simultaneous deliveries lose the race in
Postgres instead of both passing the check and both creating a workflow.

**Evidence.** The redacted payload is retained so a support engineer can
answer "what exactly did Salesforce send us?" during an incident without
asking the customer to reproduce it. That question is unanswerable from logs
alone once a payload has been transformed by two systems.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import InboundEventStatus, ProviderType, enum_values

if TYPE_CHECKING:
    from app.models.workflow import WorkflowInstance


class InboundEvent(Base):
    __tablename__ = "inbound_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Who delivered it to us — n8n for the Salesforce path, since n8n is
    # what actually makes the HTTP call. The originating system is recorded
    # separately in `source_system` so "Salesforce change, delivered by
    # n8n" is expressible; collapsing the two would lose the ability to
    # tell a broken n8n from a broken Salesforce.
    delivered_by: Mapped[ProviderType] = mapped_column(
        SAEnum(ProviderType, name="provider_type", values_callable=enum_values), nullable=False
    )
    source_system: Mapped[ProviderType] = mapped_column(
        SAEnum(ProviderType, name="provider_type", values_callable=enum_values),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Supplied by the caller (n8n derives it from the Salesforce record ID
    # plus the change that triggered it — see the n8n workflow export).
    # Unique, which is the entire duplicate-protection mechanism.
    idempotency_key: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Redacted before persisting — see core/provider_errors.redact_mapping.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[InboundEventStatus] = mapped_column(
        SAEnum(InboundEventStatus, name="inbound_event_status", values_callable=enum_values),
        nullable=False,
        default=InboundEventStatus.RECEIVED,
        index=True,
    )
    # The workflow this event started, when it started one. Nullable
    # because a duplicate or rejected delivery never starts anything, and
    # because some event types are recorded for audit without triggering a
    # workflow at all.
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_instances.id"), nullable=True, index=True
    )
    # For a DUPLICATE row: which original it duplicates. Turns "we got this
    # twice" from a log line into a navigable link in the support console.
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("inbound_events.id"), nullable=True
    )
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow_instance: Mapped["WorkflowInstance | None"] = relationship()
