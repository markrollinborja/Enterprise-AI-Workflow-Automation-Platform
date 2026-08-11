"""Resolves a connection row into the adapter that can talk to it.

The registry's only real decision is live-versus-simulated, and the
important behavior is what happens when a live adapter does not exist yet.

Phase 1 ships no live adapters — Salesforce arrives in Phase 2, Keycloak in
Phase 3, Graph in Phase 4. A registry that quietly fell back to the simulator
for `mode=LIVE` would be the single most damaging shortcut available in this
project: every dashboard, every health record, and eventually the portfolio
write-up would claim a live integration that never existed. Instead an
unimplemented live adapter raises `ProviderConfigurationError`, which surfaces
as an unhealthy connection with the reason stated plainly.

That is also why `ProviderMode` is persisted per connection rather than read
from a global setting: "what did this platform actually verify against a real
provider?" has to be answerable from the data, not from a config file's
current value.
"""

from app.core.config import get_settings
from app.core.provider_errors import ProviderConfigurationError
from app.models.enums import ProviderMode, ProviderType
from app.models.integration import IntegrationConnection
from app.services.integrations.providers.base import Provider
from app.services.integrations.providers.salesforce_live import SalesforceLiveProvider
from app.services.integrations.providers.salesforce_simulated import (
    SalesforceSimulatedProvider,
)
from app.services.integrations.providers.simulated import SimulatedProvider

# Live adapters, keyed by ProviderType value. Salesforce lands in Phase 2;
# Keycloak, SCIM and Graph follow in Phases 3-4.
_LIVE_ADAPTERS: dict[str, type[Provider]] = {
    ProviderType.SALESFORCE.value: SalesforceLiveProvider,
}

# Provider-specific simulators. A provider without an entry here falls back
# to the generic SimulatedProvider, which is correct for anything whose
# failure surface is not yet distinctive enough to be worth its own class.
_SIMULATORS: dict[str, type[SimulatedProvider]] = {
    ProviderType.SALESFORCE.value: SalesforceSimulatedProvider,
}


def resolve(connection: IntegrationConnection) -> Provider:
    """Return the adapter for this connection.

    Raises `ProviderConfigurationError` if the connection asks for a live
    adapter that does not exist yet — never silently simulates.
    """
    if connection.mode is ProviderMode.SIMULATED:
        simulator_cls = _SIMULATORS.get(connection.provider.value, SimulatedProvider)
        return simulator_cls(
            provider_type=connection.provider,
            connection_key=connection.connection_key,
            base_url=connection.base_url,
            config=dict(connection.config or {}),
        )

    adapter_cls = _LIVE_ADAPTERS.get(connection.provider.value)
    if adapter_cls is None:
        raise ProviderConfigurationError(
            f"No live adapter implemented for provider '{connection.provider.value}'. "
            f"Set mode=simulated, or implement the adapter.",
            provider=connection.provider.value,
            operation="resolve_provider",
        )

    return adapter_cls(
        connection_key=connection.connection_key,
        # Credentials come from the environment, never from the connection
        # row — the row holds only `credential_ref`, the *name* of the
        # variable (ADR-0016). Resolving them here rather than inside each
        # adapter keeps every adapter free of configuration lookups and
        # makes this the single place to audit how secrets reach a
        # provider.
        base_url=connection.base_url or _default_base_url(connection.provider),
        config=dict(connection.config or {}),
        **_live_credentials(connection.provider),
    )


def _default_base_url(provider: ProviderType) -> str | None:
    """Fall back to the configured instance URL when the row has none.

    A connection row may legitimately omit base_url when there is only one
    instance of that provider for the whole platform, which is the common
    case in this project. Seeded rows set it explicitly; this covers the
    hand-created ones.
    """
    settings = get_settings()
    if provider is ProviderType.SALESFORCE:
        return settings.salesforce_instance_url or None
    return None


def _live_credentials(provider: ProviderType) -> dict[str, str | None]:
    """Provider-specific credential kwargs, read from settings.

    Returns empty for providers whose adapters take no credentials. Each
    adapter validates its own requirements and raises
    ProviderConfigurationError with a specific message, so a missing secret
    surfaces as an unhealthy connection with an actionable reason rather
    than a TypeError about a missing argument.
    """
    settings = get_settings()
    if provider is ProviderType.SALESFORCE:
        return {
            "client_id": settings.salesforce_client_id or None,
            "client_secret": settings.salesforce_client_secret or None,
        }
    return {}


def register_live_adapter(provider_value: str, adapter_cls: type[Provider]) -> None:
    """Register a live adapter. Called by each provider package as it lands.

    A function rather than direct dict mutation so the registration point is
    greppable — "which providers have live adapters?" should have one
    answer, findable in one search, rather than being scattered across
    import side effects.
    """
    _LIVE_ADAPTERS[provider_value] = adapter_cls


def live_adapter_providers() -> tuple[str, ...]:
    """Which providers currently have a live adapter.

    Feeds the live-versus-simulated disclosure in the README and the
    portfolio evidence document, so that claim is generated from the code
    rather than maintained by hand and drifting.
    """
    return tuple(sorted(_LIVE_ADAPTERS))
