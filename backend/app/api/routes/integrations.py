"""Integration connection endpoints — Module 1's HTTP surface.

Restricted to IT, SECURITY and ADMINISTRATOR. Deliberately narrower than the
employee directory or application catalog, which any authenticated user can
read: those describe what a person can request, while this describes the
platform's own credentials, endpoints, and failure history. An employee has
no reason to learn which Salesforce instance we call or that its token
expires on Thursday, and reconnaissance value is the whole argument.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.integration import (
    HealthCheckResultResponse,
    IntegrationConnectionResponse,
)
from app.services.integrations import connection_service

router = APIRouter(prefix="/integrations", tags=["integrations"])

# One definition, applied to every route below — an operator-facing surface
# where a future route silently defaulting to "any authenticated user"
# would be a quiet privilege escalation.
_OPERATOR_ROLES = (UserRole.IT, UserRole.SECURITY, UserRole.ADMINISTRATOR)


@router.get("/connections", response_model=list[IntegrationConnectionResponse])
def list_connections(
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_OPERATOR_ROLES)),
) -> list[IntegrationConnectionResponse]:
    """The integration health grid — every connection and its current state."""
    connections = connection_service.list_connections(db)
    return [IntegrationConnectionResponse.model_validate(c) for c in connections]


@router.get("/connections/{connection_id}", response_model=IntegrationConnectionResponse)
def get_connection(
    connection_id: UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_OPERATOR_ROLES)),
) -> IntegrationConnectionResponse:
    connection = connection_service.get_connection(db, connection_id)
    return IntegrationConnectionResponse.model_validate(connection)


@router.get(
    "/connections/{connection_id}/health-history",
    response_model=list[HealthCheckResultResponse],
)
def get_health_history(
    connection_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_OPERATOR_ROLES)),
) -> list[HealthCheckResultResponse]:
    """The incident timeline for one connection — when it started failing
    and what it said, which is the question during an incident."""
    results = connection_service.get_health_history(db, connection_id, limit=limit)
    return [HealthCheckResultResponse.model_validate(r) for r in results]


@router.post(
    "/connections/{connection_id}/health-check",
    response_model=HealthCheckResultResponse,
)
def run_health_check(
    connection_id: UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(UserRole.IT, UserRole.ADMINISTRATOR)),
) -> HealthCheckResultResponse:
    """Run a check now and return the result.

    Returns 200 even when the provider is down. The request asked "check
    this connection", and the check ran — a 502 here would conflate "the
    provider is unhealthy" with "this endpoint failed", and a support tool
    that errors when it finds a problem is the opposite of useful.

    Narrower than the read routes: SECURITY can see integration state but
    not trigger outbound calls to third parties. Triggering a check is an
    action with an external side effect, however small, and read access
    should not imply it.
    """
    result = connection_service.check_connection_health(db, connection_id)
    return HealthCheckResultResponse.model_validate(result)
