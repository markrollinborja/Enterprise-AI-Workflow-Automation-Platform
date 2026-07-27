from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import RiskLevel


class ApplicationResponse(BaseModel):
    """No Create/Update schema — the catalog is seed-managed in V1, not
    user-editable through the API. An admin-facing "add an application"
    route is a reasonable V2 feature, not something this phase needs."""

    id: UUID
    name: str
    description: str
    risk_level: RiskLevel
    created_at: datetime
