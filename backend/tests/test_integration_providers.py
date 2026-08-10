"""Provider adapters, registry, and the health-check API — V2 Module 1.

The most consequential test in this file is
`test_live_mode_without_an_adapter_refuses_to_simulate`. A registry that
quietly fell back to the simulator would make every dashboard, every health
record, and eventually the portfolio write-up claim a live integration that
never existed. That is the one failure mode in this module that damages
something other than the software.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.provider_errors import ProviderConfigurationError
from app.core.security import hash_password
from app.models.enums import (
    ConnectionStatus,
    HealthStatus,
    ProviderMode,
    ProviderType,
    UserRole,
)
from app.models.integration import IntegrationConnection
from app.models.user import User
from app.services.integrations.providers import registry
from app.services.integrations.providers.simulated import SCENARIO_NAMES, SimulatedProvider

TEST_PASSWORD = "CorrectHorse123!"


def _auth_headers(client: TestClient, db: Session, role: UserRole, email: str) -> dict[str, str]:
    db.add(
        User(
            email=email,
            hashed_password=hash_password(TEST_PASSWORD),
            full_name="Test User",
            role=role,
        )
    )
    db.commit()
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _connection(db: Session, **overrides: object) -> IntegrationConnection:
    fields: dict[str, object] = {
        "provider": ProviderType.SALESFORCE,
        "connection_key": f"sf-{uuid.uuid4().hex[:8]}",
        "display_name": "Salesforce",
        "mode": ProviderMode.SIMULATED,
        "status": ConnectionStatus.ENABLED,
        "config": {},
    }
    fields.update(overrides)
    connection = IntegrationConnection(**fields)
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


class TestSimulatedProvider:
    def test_healthy_by_default(self) -> None:
        provider = SimulatedProvider(
            provider_type=ProviderType.SALESFORCE, connection_key="sf-dev"
        )
        outcome = provider.check_health()
        assert outcome.status is HealthStatus.HEALTHY
        assert outcome.succeeded is True
        assert outcome.detail["simulated"] is True

    @pytest.mark.parametrize("scenario", SCENARIO_NAMES)
    def test_every_documented_scenario_produces_a_failure(self, scenario: str) -> None:
        """Parametrized over the exported names because those names appear
        in runbooks — a scenario that silently stopped failing would make a
        runbook lie."""
        provider = SimulatedProvider(
            provider_type=ProviderType.SALESFORCE,
            connection_key="sf-dev",
            config={"simulate_failure": scenario},
        )
        outcome = provider.check_health()
        assert outcome.succeeded is False
        assert outcome.error_type is not None

    def test_rate_limiting_is_degraded_not_unhealthy(self) -> None:
        """The provider is up and our credentials are valid — we are being
        asked to slow down. Paging someone for that is a false alarm."""
        provider = SimulatedProvider(
            provider_type=ProviderType.SALESFORCE,
            connection_key="sf-dev",
            config={"simulate_failure": "rate_limited", "retry_after_seconds": 12},
        )
        outcome = provider.check_health()
        assert outcome.status is HealthStatus.DEGRADED
        assert outcome.retry_after_seconds == 12

    def test_expired_token_reports_a_retryable_failure(self) -> None:
        provider = SimulatedProvider(
            provider_type=ProviderType.KEYCLOAK,
            connection_key="kc",
            config={"simulate_failure": "expired_token"},
        )
        outcome = provider.check_health()
        assert outcome.status is HealthStatus.UNHEALTHY
        assert outcome.error_type == "ProviderAuthError"

    def test_unknown_scenario_name_fails_loudly(self) -> None:
        """Silently succeeding would make a Failure Lab exercise look like a
        passing health check — the most misleading outcome available."""
        provider = SimulatedProvider(
            provider_type=ProviderType.SALESFORCE,
            connection_key="sf-dev",
            config={"simulate_failure": "typo_scenario"},
        )
        outcome = provider.check_health()
        assert outcome.succeeded is False
        assert outcome.error_type == "ProviderConfigurationError"

    def test_check_health_never_raises_even_on_an_adapter_bug(self) -> None:
        """One broken adapter must not take down a sweep across eight
        providers."""

        class BrokenProvider(SimulatedProvider):
            def _perform_health_check(self) -> dict[str, object]:
                raise ZeroDivisionError("adapter bug")

        outcome = BrokenProvider(
            provider_type=ProviderType.JIRA, connection_key="jira"
        ).check_health()
        assert outcome.succeeded is False
        assert outcome.error_type == "ZeroDivisionError"

    def test_duration_is_always_recorded(self) -> None:
        """Including on the failure path — latency of failing calls is
        exactly what you want when diagnosing a timeout."""
        provider = SimulatedProvider(
            provider_type=ProviderType.SLACK,
            connection_key="slack",
            config={"simulate_failure": "timeout"},
        )
        assert provider.check_health().duration_ms >= 0

    def test_name_identifies_the_specific_connection(self) -> None:
        """A platform with two Salesforce connections needs "which one?"
        answered by the metric label, not a follow-up query."""
        provider = SimulatedProvider(
            provider_type=ProviderType.SALESFORCE, connection_key="sandbox"
        )
        assert provider.name == "salesforce/sandbox"


class TestRegistry:
    def test_simulated_mode_resolves_to_the_simulator(self, db_session: Session) -> None:
        connection = _connection(db_session, mode=ProviderMode.SIMULATED)
        assert isinstance(registry.resolve(connection), SimulatedProvider)

    def test_simulator_is_told_which_provider_it_stands_in_for(
        self, db_session: Session
    ) -> None:
        connection = _connection(db_session, provider=ProviderType.MICROSOFT_GRAPH)
        assert registry.resolve(connection).provider_type is ProviderType.MICROSOFT_GRAPH

    def test_live_mode_without_an_adapter_refuses_to_simulate(
        self, db_session: Session
    ) -> None:
        """The integrity test for the whole module. No live adapters exist
        in Phase 1, and asking for one must fail loudly rather than quietly
        returning simulated data that would be recorded as real."""
        connection = _connection(db_session, mode=ProviderMode.LIVE)
        with pytest.raises(ProviderConfigurationError):
            registry.resolve(connection)

    def test_no_live_adapters_are_claimed_in_phase_1(self) -> None:
        """Feeds the live-versus-simulated disclosure. If this ever fails,
        the README's claim has to change in the same commit."""
        assert registry.live_adapter_providers() == ()


class TestHealthCheckEndpoint:
    def test_it_can_run_a_check_and_gets_a_recorded_result(
        self, client: TestClient, db_session: Session
    ) -> None:
        connection = _connection(db_session)
        headers = _auth_headers(client, db_session, UserRole.IT, "it-hc@cordant.io")

        response = client.post(
            f"/integrations/connections/{connection.id}/health-check", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["succeeded"] is True
        assert body["status"] == "healthy"
        assert body["correlation_id"]

    def test_a_failing_provider_still_returns_200(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A support tool that errors when it finds a problem is the
        opposite of useful — the check ran, which is what was asked."""
        connection = _connection(db_session, config={"simulate_failure": "unreachable"})
        headers = _auth_headers(client, db_session, UserRole.IT, "it-hc-fail@cordant.io")

        response = client.post(
            f"/integrations/connections/{connection.id}/health-check", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["succeeded"] is False
        assert response.json()["status"] == "unhealthy"

    def test_failure_then_success_resets_the_failure_run(
        self, client: TestClient, db_session: Session
    ) -> None:
        connection = _connection(db_session, config={"simulate_failure": "unreachable"})
        headers = _auth_headers(client, db_session, UserRole.IT, "it-hc-reset@cordant.io")
        url = f"/integrations/connections/{connection.id}/health-check"

        client.post(url, headers=headers)
        client.post(url, headers=headers)
        db_session.refresh(connection)
        assert connection.consecutive_failure_count == 2
        assert connection.last_error_summary is not None

        connection.config = {}
        db_session.commit()
        client.post(url, headers=headers)
        db_session.refresh(connection)

        assert connection.consecutive_failure_count == 0
        assert connection.last_error_summary is None
        assert connection.health_status is HealthStatus.HEALTHY

    def test_disabled_connection_is_not_checked(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Nothing was observed, so nothing is claimed — UNKNOWN rather
        than inventing a colour for a connection nobody asked us to use."""
        connection = _connection(db_session, status=ConnectionStatus.DISABLED)
        headers = _auth_headers(client, db_session, UserRole.IT, "it-hc-disabled@cordant.io")

        response = client.post(
            f"/integrations/connections/{connection.id}/health-check", headers=headers
        )
        assert response.json()["status"] == "unknown"
        assert response.json()["error_type"] == "ConnectionDisabled"

    def test_history_accumulates_and_is_newest_first(
        self, client: TestClient, db_session: Session
    ) -> None:
        connection = _connection(db_session)
        headers = _auth_headers(client, db_session, UserRole.IT, "it-hist@cordant.io")
        for _ in range(3):
            client.post(
                f"/integrations/connections/{connection.id}/health-check", headers=headers
            )

        response = client.get(
            f"/integrations/connections/{connection.id}/health-history", headers=headers
        )
        results = response.json()
        assert len(results) == 3
        assert results[0]["checked_at"] >= results[-1]["checked_at"]

    def test_history_for_an_unknown_connection_is_404_not_empty(
        self, client: TestClient, db_session: Session
    ) -> None:
        """"No history" and "no such connection" are different answers."""
        headers = _auth_headers(client, db_session, UserRole.IT, "it-404@cordant.io")
        response = client.get(
            f"/integrations/connections/{uuid.uuid4()}/health-history", headers=headers
        )
        assert response.status_code == 404


class TestAuthorization:
    @pytest.mark.parametrize(
        "role", [UserRole.IT, UserRole.SECURITY, UserRole.ADMINISTRATOR]
    )
    def test_operator_roles_can_read_connections(
        self, client: TestClient, db_session: Session, role: UserRole
    ) -> None:
        headers = _auth_headers(
            client, db_session, role, f"op-{role.value}@cordant.io"
        )
        assert client.get("/integrations/connections", headers=headers).status_code == 200

    @pytest.mark.parametrize(
        "role", [UserRole.EMPLOYEE, UserRole.MANAGER, UserRole.HR]
    )
    def test_non_operator_roles_are_refused(
        self, client: TestClient, db_session: Session, role: UserRole
    ) -> None:
        """An employee has no reason to learn which Salesforce instance we
        call or when its token expires."""
        headers = _auth_headers(
            client, db_session, role, f"nonop-{role.value}@cordant.io"
        )
        assert client.get("/integrations/connections", headers=headers).status_code == 403

    def test_security_can_read_but_cannot_trigger_a_check(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Triggering a check has an external side effect, however small.
        Read access should not imply it."""
        connection = _connection(db_session)
        headers = _auth_headers(client, db_session, UserRole.SECURITY, "sec-rbac@cordant.io")

        assert client.get("/integrations/connections", headers=headers).status_code == 200
        assert (
            client.post(
                f"/integrations/connections/{connection.id}/health-check", headers=headers
            ).status_code
            == 403
        )

    def test_unauthenticated_access_is_refused(self, client: TestClient) -> None:
        assert client.get("/integrations/connections").status_code == 403


class TestResponseSafety:
    def test_credential_ref_and_config_are_never_serialized(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Neither is needed to answer "is this healthy?", and
        credential_ref would tell a reader exactly which variable to go
        after."""
        _connection(
            db_session,
            credential_ref="SALESFORCE_CLIENT_SECRET",
            config={"simulate_failure": "none", "instance_url": "https://example.my.salesforce.com"},
        )
        headers = _auth_headers(client, db_session, UserRole.IT, "it-safety@cordant.io")

        body = client.get("/integrations/connections", headers=headers).text
        assert "credential_ref" not in body
        assert "SALESFORCE_CLIENT_SECRET" not in body
        assert "instance_url" not in body

    def test_mode_is_exposed_so_simulated_health_is_never_mistaken_for_live(
        self, client: TestClient, db_session: Session
    ) -> None:
        _connection(db_session, mode=ProviderMode.SIMULATED)
        headers = _auth_headers(client, db_session, UserRole.IT, "it-mode@cordant.io")

        connections = client.get("/integrations/connections", headers=headers).json()
        assert all(c["mode"] == "simulated" for c in connections)
