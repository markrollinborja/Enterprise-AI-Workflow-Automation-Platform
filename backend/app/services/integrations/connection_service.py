"""Integration connection management — the service layer for Module 1.

Sits between the routes and the provider adapters: resolves a connection to
its adapter, runs the check, records the result, and logs the outcome with
the fields the observability stack expects.
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id
from app.core.exceptions import NotFoundError
from app.core.provider_errors import ProviderError, redact_mapping, summarize
from app.models.enums import ConnectionStatus, HealthStatus
from app.models.integration import HealthCheckResult, IntegrationConnection
from app.repositories import integration_connection_repo
from app.services.integrations.providers import registry
from app.services.integrations.providers.base import HealthCheckOutcome

logger = logging.getLogger(__name__)


def list_connections(db: Session) -> list[IntegrationConnection]:
    return integration_connection_repo.list_all(db)


def get_connection(db: Session, connection_id: UUID) -> IntegrationConnection:
    connection = integration_connection_repo.get_by_id(db, connection_id)
    if connection is None:
        raise NotFoundError(f"Integration connection {connection_id} not found")
    return connection


def get_health_history(
    db: Session, connection_id: UUID, *, limit: int = 50
) -> list[HealthCheckResult]:
    # Resolve first so an unknown ID is a 404 rather than an empty list —
    # "no history" and "no such connection" are different answers and a
    # support engineer needs to be able to tell them apart.
    get_connection(db, connection_id)
    return integration_connection_repo.list_health_history(db, connection_id, limit=limit)


def check_connection_health(db: Session, connection_id: UUID) -> HealthCheckResult:
    """Run one health check and record it.

    Never raises on provider failure — a failed check is a recorded result,
    not an error response. The endpoint that triggers this returns 200 with
    an unhealthy result, because "the check ran and the provider is down" is
    a successful execution of the request that was made.
    """
    connection = get_connection(db, connection_id)
    correlation_id = get_correlation_id()

    if connection.status is ConnectionStatus.DISABLED:
        # Not an error, and not a health check either. Recorded as UNKNOWN
        # rather than HEALTHY or UNHEALTHY: nothing was observed, and
        # inventing an observation for a connection nobody asked us to use
        # would put a misleading colour on the dashboard.
        outcome = HealthCheckOutcome(
            status=HealthStatus.UNKNOWN,
            succeeded=False,
            duration_ms=0,
            error_summary="Connection is disabled; no check performed",
            error_type="ConnectionDisabled",
        )
    else:
        outcome = _run_check(connection)

    result = integration_connection_repo.record_health_result(
        db,
        connection,
        status=outcome.status,
        succeeded=outcome.succeeded,
        duration_ms=outcome.duration_ms,
        correlation_id=correlation_id,
        error_summary=outcome.error_summary,
        error_type=outcome.error_type,
    )

    _log_outcome(connection, outcome)
    return result


def _run_check(connection: IntegrationConnection) -> HealthCheckOutcome:
    """Resolve the adapter and check it.

    Adapter resolution is inside the try because it can legitimately fail —
    asking for a live adapter that does not exist yet is a
    ProviderConfigurationError, and that is a real, reportable unhealthy
    state rather than a crash. See registry.resolve().
    """
    try:
        provider = registry.resolve(connection)
    except ProviderError as exc:
        return HealthCheckOutcome(
            status=HealthStatus.UNHEALTHY,
            succeeded=False,
            duration_ms=0,
            error_summary=exc.message,
            error_type=type(exc).__name__,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return HealthCheckOutcome(
            status=HealthStatus.UNHEALTHY,
            succeeded=False,
            duration_ms=0,
            error_summary=summarize(exc),
            error_type=type(exc).__name__,
        )

    return provider.check_health()


def _log_outcome(connection: IntegrationConnection, outcome: HealthCheckOutcome) -> None:
    """One log line per check, uniformly shaped.

    `extra` fields become top-level JSON keys (see app/core/logging.py), so
    "error rate by provider" and "p95 health-check latency by provider" are
    queries rather than log-scraping. Detail is redacted on the way out even
    though adapters are not supposed to put secrets there — defence in
    depth, since this is the last point before the value leaves the process.
    """
    context = {
        "provider": connection.provider.value,
        "connection_key": connection.connection_key,
        "mode": connection.mode.value,
        "health_status": outcome.status.value,
        "duration_ms": outcome.duration_ms,
        "consecutive_failures": connection.consecutive_failure_count,
        "detail": redact_mapping(outcome.detail),
    }

    if outcome.succeeded:
        logger.info("Health check succeeded", extra=context)
    else:
        logger.warning(
            "Health check failed",
            extra={**context, "error_type": outcome.error_type},
        )
