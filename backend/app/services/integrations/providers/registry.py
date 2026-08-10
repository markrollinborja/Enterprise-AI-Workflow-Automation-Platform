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

from app.core.provider_errors import ProviderConfigurationError
from app.models.enums import ProviderMode
from app.models.integration import IntegrationConnection
from app.services.integrations.providers.base import Provider
from app.services.integrations.providers.simulated import SimulatedProvider

# Live adapters register themselves here as they are built, keyed by
# ProviderType. Empty in Phase 1 — deliberately, and visibly.
_LIVE_ADAPTERS: dict[str, type[Provider]] = {}


def resolve(connection: IntegrationConnection) -> Provider:
    """Return the adapter for this connection.

    Raises `ProviderConfigurationError` if the connection asks for a live
    adapter that does not exist yet — never silently simulates.
    """
    if connection.mode is ProviderMode.SIMULATED:
        return SimulatedProvider(
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
        base_url=connection.base_url,
        config=dict(connection.config or {}),
    )


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
