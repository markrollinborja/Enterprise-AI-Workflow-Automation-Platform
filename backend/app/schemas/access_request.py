from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import InstanceStatus, RiskLevel


class AccessRequestCreate(BaseModel):
    """`employee_id` is deliberately not a field here — it's derived from
    the authenticated caller's own linked Employee record (see
    services/access_requests/service.py), not taken from the request body.
    Accepting it as client input would let any authenticated user submit a
    request "as" someone else."""

    application_id: UUID
    justification: str = Field(min_length=10, max_length=2000)


class AccessRequestResponse(BaseModel):
    """A purpose-built shape, not the raw WorkflowInstance — surfaces
    exactly what a submitter needs to see: what the rules engine decided
    (computed_risk_level, auto_approved) and where the workflow stands
    right now."""

    workflow_instance_id: UUID
    application_id: UUID
    application_name: str
    justification: str
    computed_risk_level: RiskLevel
    auto_approved: bool
    status: InstanceStatus
    current_step_key: str | None
