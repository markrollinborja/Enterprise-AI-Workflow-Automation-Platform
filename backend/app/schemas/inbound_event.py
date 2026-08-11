"""Response schema for inbound events.

The payload is included, unlike `IntegrationConnection.config` — and the
difference is deliberate. Answering "what exactly did Salesforce send us?"
is the whole reason this table exists, and a support engineer who cannot see
the payload has to go ask the customer to reproduce the problem. It is safe
to expose because it was redacted at ingestion (see
ingestion_service.ingest_event), and the routes that return it are restricted
to IT, Security and Administrator.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import InboundEventStatus, ProviderType


class InboundEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delivered_by: ProviderType
    source_system: ProviderType
    event_type: str
    idempotency_key: str
    correlation_id: str
    payload: dict[str, Any]
    status: InboundEventStatus
    workflow_instance_id: uuid.UUID | None
    duplicate_of_id: uuid.UUID | None
    error_summary: str | None
    received_at: datetime
    processed_at: datetime | None
