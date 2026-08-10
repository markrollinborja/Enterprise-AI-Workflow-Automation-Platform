from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import HealthStatus, ProviderType
from app.models.integration import HealthCheckResult, IntegrationConnection


def get_by_id(db: Session, connection_id: UUID) -> IntegrationConnection | None:
    return db.get(IntegrationConnection, connection_id)


def get_by_provider_and_key(
    db: Session, provider: ProviderType, connection_key: str
) -> IntegrationConnection | None:
    return db.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.provider == provider,
            IntegrationConnection.connection_key == connection_key,
        )
    ).first()


def list_all(db: Session) -> list[IntegrationConnection]:
    """Ordered by provider then key so the health grid has a stable layout.

    An unstable order makes a dashboard unreadable — a support engineer
    scanning for a red row should find it in the same place every time.
    """
    return list(
        db.scalars(
            select(IntegrationConnection).order_by(
                IntegrationConnection.provider, IntegrationConnection.connection_key
            )
        )
    )


def create(db: Session, **fields: Any) -> IntegrationConnection:
    connection = IntegrationConnection(**fields)
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def record_health_result(
    db: Session,
    connection: IntegrationConnection,
    *,
    status: HealthStatus,
    succeeded: bool,
    duration_ms: int,
    correlation_id: str,
    error_summary: str | None = None,
    error_type: str | None = None,
) -> HealthCheckResult:
    """Append one history row and roll the connection's current state forward.

    Both in one transaction on purpose. A history row without the matching
    summary update leaves the dashboard showing stale health; a summary
    update without the history row loses the incident timeline. They are one
    fact recorded in two shapes, so they commit together or not at all.
    """
    now = datetime.now(UTC)

    result = HealthCheckResult(
        connection_id=connection.id,
        status=status,
        succeeded=succeeded,
        duration_ms=duration_ms,
        error_summary=error_summary,
        error_type=error_type,
        correlation_id=correlation_id,
        config_version=connection.config_version,
    )
    db.add(result)

    connection.health_status = status
    connection.last_health_check_at = now
    if succeeded:
        connection.last_success_at = now
        # Cleared on success, not decremented: the column answers "how many
        # times in a row", and one success ends the run by definition.
        connection.consecutive_failure_count = 0
        connection.last_error_summary = None
    else:
        connection.last_failure_at = now
        connection.consecutive_failure_count += 1
        connection.last_error_summary = error_summary

    db.commit()
    db.refresh(result)
    return result


def list_health_history(
    db: Session, connection_id: UUID, *, limit: int = 50
) -> list[HealthCheckResult]:
    """Most recent first, bounded — this table grows without limit and no
    caller wants all of it."""
    return list(
        db.scalars(
            select(HealthCheckResult)
            .where(HealthCheckResult.connection_id == connection_id)
            .order_by(HealthCheckResult.checked_at.desc())
            .limit(limit)
        )
    )


def find_by_correlation_id(db: Session, correlation_id: str) -> list[HealthCheckResult]:
    """Every check that belonged to one sweep or one investigation.

    The support console's primary lookup (Module 8): paste the ID from a
    Slack alert, get everything that happened under it.
    """
    return list(
        db.scalars(
            select(HealthCheckResult)
            .where(HealthCheckResult.correlation_id == correlation_id)
            .order_by(HealthCheckResult.checked_at.desc())
        )
    )
