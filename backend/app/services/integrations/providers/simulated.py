"""The simulated provider — a first-class implementation, not a stub.

ADR-0016's position is that a simulator which only ever succeeds is worse
than no simulator, because it trains both the code and its author to assume
the happy path. This one reproduces the failures that actually happen to
integrations in the wild, on demand, deterministically:

- an expired access token (refreshable — a retry after refresh works)
- a revoked grant (not refreshable — retrying is pointless)
- rate limiting, with the provider's own Retry-After guidance
- a missing permission or scope
- a timeout, where the request may have succeeded upstream
- an unreachable host
- a misconfigured connection

That list is the input to the Failure Lab (Module 9) and to the contract
tests every live adapter must also satisfy. It exists in Phase 1, before any
live adapter, deliberately: writing the failure surface first is what stops
the live adapters from being written against an imagined happy path.

Selection is by the connection's own `config["simulate_failure"]`, so a
scenario is reproduced by configuring a connection rather than by patching
code — which is what makes it demonstrable in a UI and usable in a runbook.
"""

from collections.abc import Callable
from typing import Any

from app.core.provider_errors import (
    PermanentProviderError,
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TransientProviderError,
)
from app.models.enums import ProviderMode, ProviderType
from app.services.integrations.providers.base import Provider

# Config key a connection sets to make this simulator fail in a specific,
# named way. Absent or "none" means the check succeeds.
SIMULATE_FAILURE_KEY = "simulate_failure"


class SimulatedProvider(Provider):
    """Stands in for any external system, reproducing realistic failures.

    One class serves every provider type rather than one simulator per
    provider: at Phase 1 the failure surface is genuinely identical across
    Salesforce, Graph, Keycloak and the rest — expired token, rate limit,
    missing permission, timeout. Provider-specific simulators are worth
    writing when a provider has genuinely distinctive behavior to reproduce
    (Salesforce's duplicate-event delivery, SCIM's 409 conflict), and those
    arrive with their own phases as subclasses of this one.
    """

    mode = ProviderMode.SIMULATED

    def __init__(self, *, provider_type: ProviderType, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Unlike a live adapter, which is bound to one system at import
        # time, the simulator is told what it is standing in for — that is
        # what lets a single class cover all eight provider types.
        self.provider_type = provider_type

    def _perform_health_check(self) -> dict[str, Any]:
        scenario = str(self.config.get(SIMULATE_FAILURE_KEY, "none")).lower()

        if scenario != "none":
            raiser = _SCENARIOS.get(scenario)
            if raiser is None:
                # An unrecognised scenario name is a configuration mistake,
                # and silently succeeding would make a Failure Lab exercise
                # look like a passing health check — the single most
                # misleading outcome available here.
                raise ProviderConfigurationError(
                    f"Unknown simulate_failure scenario: {scenario}",
                    provider=self.provider_type.value,
                    operation="health_check",
                )
            raiser(self)

        return {
            "simulated": True,
            "provider": self.provider_type.value,
            "connection_key": self.connection_key,
        }


def _expired_token(provider: SimulatedProvider) -> None:
    raise ProviderAuthError(
        "Session expired or invalid",
        refreshable=True,
        provider=provider.provider_type.value,
        operation="health_check",
        status_code_from_provider=401,
    )


def _revoked_grant(provider: SimulatedProvider) -> None:
    raise ProviderAuthError(
        "Authorization revoked for this client",
        refreshable=False,
        provider=provider.provider_type.value,
        operation="health_check",
        status_code_from_provider=401,
    )


def _rate_limited(provider: SimulatedProvider) -> None:
    raise ProviderRateLimitError(
        "REQUEST_LIMIT_EXCEEDED",
        provider=provider.provider_type.value,
        operation="health_check",
        status_code_from_provider=429,
        retry_after_seconds=float(provider.config.get("retry_after_seconds", 30)),
    )


def _missing_permission(provider: SimulatedProvider) -> None:
    raise PermanentProviderError(
        "INSUFFICIENT_ACCESS: the integration user lacks the required permission",
        provider=provider.provider_type.value,
        operation="health_check",
        status_code_from_provider=403,
    )


def _timeout(provider: SimulatedProvider) -> None:
    raise ProviderTimeoutError(
        "Read timed out waiting for provider response",
        provider=provider.provider_type.value,
        operation="health_check",
    )


def _unreachable(provider: SimulatedProvider) -> None:
    raise TransientProviderError(
        "Connection refused",
        provider=provider.provider_type.value,
        operation="health_check",
    )


def _misconfigured(provider: SimulatedProvider) -> None:
    raise ProviderConfigurationError(
        "Connection is missing required configuration",
        provider=provider.provider_type.value,
        operation="health_check",
    )


# Named scenarios, referenced by connection config and by Failure Lab
# runbooks. Names are part of the platform's documented surface — renaming
# one breaks a runbook, so they are deliberately plain.
_SCENARIOS: dict[str, Callable[[SimulatedProvider], None]] = {
    "expired_token": _expired_token,
    "revoked_grant": _revoked_grant,
    "rate_limited": _rate_limited,
    "missing_permission": _missing_permission,
    "timeout": _timeout,
    "unreachable": _unreachable,
    "misconfigured": _misconfigured,
}

SCENARIO_NAMES = tuple(sorted(_SCENARIOS))
