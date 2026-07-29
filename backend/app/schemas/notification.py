from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    """`from_attributes` pass-through — unlike ApprovalRequestResponse, a
    Notification needs no joined-relationship lookups (workflow_instance_id
    is enough for the frontend to link out to the workflow detail page,
    same UUID it already uses elsewhere)."""

    model_config = {"from_attributes": True}

    id: UUID
    workflow_instance_id: UUID | None
    type: str
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None
