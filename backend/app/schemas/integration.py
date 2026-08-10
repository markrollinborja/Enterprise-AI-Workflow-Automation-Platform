"""Response schemas for integration connection management.

The notable thing here is what is *absent*. `credential_ref` never leaves the
API, and neither does `config`. The model stores an environment-variable name
rather than a secret (ADR-0016), so exposing it would not leak a credential —
but it would tell a reader exactly which variable to go after, and `config`
is free-form enough that a future provider could put something sensitive in
it. Neither field is needed to answer "is this integration healthy?", which
is what these endpoints exist for, so neither is serialized.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    ConnectionStatus,
    HealthStatus,
    ProviderAuthMethod,
    ProviderMode,
    ProviderType,
)


class IntegrationConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: ProviderType
    connection_key: str
    display_name: str
    organization_ref: str | None
    status: ConnectionStatus
    # Exposed deliberately: a support engineer looking at a green health
    # indicator must be able to see whether it was a real provider or a
    # simulator that returned it. Hiding this is how a portfolio project
    # accidentally starts claiming live integrations it doesn't have.
    mode: ProviderMode
    auth_method: ProviderAuthMethod
    base_url: str | None
    health_status: HealthStatus
    last_health_check_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_summary: str | None
    consecutive_failure_count: int
    token_expires_at: datetime | None
    config_version: int
    created_at: datetime
    updated_at: datetime


class HealthCheckResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    status: HealthStatus
    succeeded: bool
    duration_ms: int | None
    error_summary: str | None
    error_type: str | None
    correlation_id: str
    config_version: int
    checked_at: datetime
