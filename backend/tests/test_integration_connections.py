"""Integration connection model — see app/models/integration.py.

The most valuable test here is the dullest one: that a row with every enum
column populated actually inserts. Every enum column in this project is one
missing `values_callable=enum_values` away from failing at runtime with
"invalid input value for enum" (see app/models/enums.py), and five new enum
types landed in one migration. A round-trip is the only thing that proves it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import (
    ConnectionStatus,
    HealthStatus,
    ProviderAuthMethod,
    ProviderMode,
    ProviderType,
)
from app.models.integration import HealthCheckResult, IntegrationConnection


def _connection(**overrides: object) -> IntegrationConnection:
    fields: dict[str, object] = {
        "provider": ProviderType.SALESFORCE,
        "connection_key": f"salesforce-{uuid.uuid4().hex[:8]}",
        "display_name": "Salesforce (developer edition)",
        "status": ConnectionStatus.ENABLED,
        "mode": ProviderMode.SIMULATED,
        "auth_method": ProviderAuthMethod.OAUTH2_JWT_BEARER,
        "health_status": HealthStatus.UNKNOWN,
        "config": {"api_version": "v62.0"},
    }
    fields.update(overrides)
    return IntegrationConnection(**fields)


class TestPersistence:
    @pytest.mark.parametrize("provider", list(ProviderType))
    def test_every_provider_value_persists(
        self, db_session: Session, provider: ProviderType
    ) -> None:
        """Parametrized over every member because the enum trap fails per
        *value*, not per column — one bad member is invisible until the day
        something writes it."""
        connection = _connection(provider=provider)
        db_session.add(connection)
        db_session.commit()
        db_session.refresh(connection)
        assert connection.provider is provider

    @pytest.mark.parametrize("auth_method", list(ProviderAuthMethod))
    def test_every_auth_method_persists(
        self, db_session: Session, auth_method: ProviderAuthMethod
    ) -> None:
        connection = _connection(auth_method=auth_method)
        db_session.add(connection)
        db_session.commit()
        assert connection.auth_method is auth_method

    @pytest.mark.parametrize("health", list(HealthStatus))
    def test_every_health_status_persists(
        self, db_session: Session, health: HealthStatus
    ) -> None:
        connection = _connection(health_status=health)
        db_session.add(connection)
        db_session.commit()
        assert connection.health_status is health

    def test_defaults_are_safe_for_a_never_checked_connection(self, db_session: Session) -> None:
        """UNKNOWN, not HEALTHY: a connection nobody has checked must not
        put a green dot on a dashboard that has verified nothing."""
        connection = IntegrationConnection(
            provider=ProviderType.JIRA,
            connection_key=f"jira-{uuid.uuid4().hex[:8]}",
            display_name="Jira Cloud",
        )
        db_session.add(connection)
        db_session.commit()
        db_session.refresh(connection)

        assert connection.health_status is HealthStatus.UNKNOWN
        assert connection.status is ConnectionStatus.ENABLED
        assert connection.mode is ProviderMode.SIMULATED
        assert connection.consecutive_failure_count == 0
        assert connection.config == {}
        assert connection.config_version == 1

    def test_same_provider_can_hold_two_connections(self, db_session: Session) -> None:
        """A sandbox and a production Salesforce are both legitimate — the
        uniqueness key is (provider, connection_key), not provider."""
        db_session.add(_connection(connection_key="salesforce-sandbox"))
        db_session.add(_connection(connection_key="salesforce-production"))
        db_session.commit()

    def test_duplicate_provider_and_key_is_rejected_by_the_database(
        self, db_session: Session
    ) -> None:
        """Enforced in Postgres, not only in the model — two rows claiming
        to be the same connection is a data-integrity problem no amount of
        service-layer care can prevent under concurrency."""
        db_session.add(_connection(connection_key="salesforce-dupe"))
        db_session.commit()
        db_session.add(_connection(connection_key="salesforce-dupe"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestUsability:
    def test_enabled_connection_is_usable(self, db_session: Session) -> None:
        assert _connection(status=ConnectionStatus.ENABLED).is_usable is True

    def test_disabled_connection_is_not_usable(self, db_session: Session) -> None:
        assert _connection(status=ConnectionStatus.DISABLED).is_usable is False

    def test_unhealthy_but_enabled_connection_is_still_attempted(self) -> None:
        """The important one. Health is a lagging indicator — refusing to
        call an UNHEALTHY connection guarantees it can never recover on its
        own. Only an operator's explicit DISABLED stops a call."""
        connection = _connection(
            status=ConnectionStatus.ENABLED, health_status=HealthStatus.UNHEALTHY
        )
        assert connection.is_usable is True


class TestHealthCheckHistory:
    def test_results_are_recorded_against_a_connection(self, db_session: Session) -> None:
        connection = _connection()
        db_session.add(connection)
        db_session.commit()

        db_session.add(
            HealthCheckResult(
                connection_id=connection.id,
                status=HealthStatus.HEALTHY,
                succeeded=True,
                duration_ms=142,
                correlation_id="mf-health-sweep-1",
                config_version=connection.config_version,
            )
        )
        db_session.commit()
        db_session.refresh(connection)

        assert len(connection.health_checks) == 1
        assert connection.health_checks[0].succeeded is True

    def test_one_sweep_shares_a_correlation_id_across_providers(
        self, db_session: Session
    ) -> None:
        """A scheduled sweep across every provider is one event, not eight
        unrelated rows — that is what the support console renders."""
        sweep_id = "mf-sweep-0400"
        for provider in (ProviderType.SALESFORCE, ProviderType.JIRA, ProviderType.SLACK):
            connection = _connection(provider=provider)
            db_session.add(connection)
            db_session.commit()
            db_session.add(
                HealthCheckResult(
                    connection_id=connection.id,
                    status=HealthStatus.HEALTHY,
                    succeeded=True,
                    correlation_id=sweep_id,
                )
            )
        db_session.commit()

        found = (
            db_session.query(HealthCheckResult)
            .filter(HealthCheckResult.correlation_id == sweep_id)
            .all()
        )
        assert len(found) == 3

    def test_failure_evidence_is_retained(self, db_session: Session) -> None:
        connection = _connection()
        db_session.add(connection)
        db_session.commit()

        db_session.add(
            HealthCheckResult(
                connection_id=connection.id,
                status=HealthStatus.UNHEALTHY,
                succeeded=False,
                error_summary="ProviderAuthError: token expired",
                error_type="ProviderAuthError",
                correlation_id="mf-health-fail-1",
            )
        )
        db_session.commit()
        db_session.refresh(connection)

        result = connection.health_checks[0]
        assert result.error_type == "ProviderAuthError"
        assert result.succeeded is False


class TestTokenExpiry:
    def test_expiry_timestamp_round_trips(self, db_session: Session) -> None:
        """A timestamp, never the token itself — this is what powers the
        "expiring in under 24h" warning instead of finding out at 3am."""
        expires = datetime.now(UTC) + timedelta(hours=12)
        connection = _connection(token_expires_at=expires)
        db_session.add(connection)
        db_session.commit()
        db_session.refresh(connection)

        assert connection.token_expires_at is not None
        assert connection.token_expires_at.tzinfo is not None
