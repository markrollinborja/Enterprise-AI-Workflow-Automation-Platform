"""The provider interface every external system implements.

`Provider.check_health()` is a template method, and that is the point of this
module. Subclasses implement only `_perform_health_check()` — the part that
is genuinely Salesforce-specific or Keycloak-specific. Timing, exception
classification, redaction, and conversion into a uniform outcome happen once,
here, for everybody.

The alternative — each adapter doing its own try/except and building its own
result — was rejected because it guarantees drift. Six adapters written over
five phases will not independently agree on what "degraded" means, will not
all remember to redact, and will not all record duration on the failure path.
Any inconsistency there lands directly in the support console and in the
Grafana integration dashboard, which are the two things this data exists to
feed. Centralising it means a new provider gets correct observability by
implementing one method.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.provider_errors import (
    ProviderError,
    ProviderRateLimitError,
    summarize,
)
from app.models.enums import HealthStatus, ProviderMode, ProviderType


@dataclass(frozen=True)
class HealthCheckOutcome:
    """The uniform result of one health check, whatever the provider.

    Frozen because it is evidence: once a check has produced an outcome,
    nothing downstream should be able to quietly adjust what was observed
    before writing it to the history table.
    """

    status: HealthStatus
    succeeded: bool
    duration_ms: int
    error_summary: str | None = None
    error_type: str | None = None
    # Non-secret provider detail worth showing a support engineer — API
    # version reached, instance URL, seconds until token expiry. Never
    # credentials: the service layer redacts this before persisting, but
    # adapters are expected not to put anything sensitive here in the first
    # place. Defence in depth, not a licence.
    detail: dict[str, Any] = field(default_factory=dict)
    # Populated only when the provider tells us when to come back (429 with
    # Retry-After). Carried through so a scheduled sweep can back off on
    # that provider specifically rather than hammering it on the next tick.
    retry_after_seconds: float | None = None


class Provider(ABC):
    """Base class for every external system adapter.

    Subclasses declare what they are (`provider_type`, `mode`) and implement
    `_perform_health_check`. Everything else is inherited.
    """

    provider_type: ProviderType
    mode: ProviderMode

    def __init__(
        self,
        *,
        connection_key: str,
        base_url: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.connection_key = connection_key
        self.base_url = base_url
        self.config = config or {}

    @property
    def name(self) -> str:
        """Stable identifier for logs and metrics — "salesforce/sandbox".

        Includes the connection key because a platform with two Salesforce
        connections needs "which one is unhealthy?" answered by the metric
        label, not by a follow-up query.
        """
        return f"{self.provider_type.value}/{self.connection_key}"

    @abstractmethod
    def _perform_health_check(self) -> dict[str, Any]:
        """Do the cheapest call that proves this connection actually works.

        Returns non-secret detail for the outcome. Raises a `ProviderError`
        subclass on failure — adapters classify their own failures, because
        only the adapter knows whether a given 403 means "token expired"
        (refreshable) or "scope missing" (permanent).

        "Cheapest call that proves it works" is doing real work in that
        sentence: a health check that only opens a TCP connection proves
        nothing about credentials, and one that runs a full query is too
        expensive to schedule every minute. The right choice is usually the
        provider's own identity or version endpoint.
        """

    def check_health(self) -> HealthCheckOutcome:
        """Run the check, and never raise.

        A health check that can throw is a health check that can take down
        the sweep that called it — one unreachable provider must not prevent
        the other seven from being checked. Every failure becomes an
        outcome instead.
        """
        started = time.monotonic()
        try:
            detail = self._perform_health_check()
        except ProviderRateLimitError as exc:
            # Degraded, not unhealthy. The provider is up and our credentials
            # are valid — we are simply being asked to slow down. Reporting
            # this as UNHEALTHY would page someone for successful operation
            # under load.
            return HealthCheckOutcome(
                status=HealthStatus.DEGRADED,
                succeeded=False,
                duration_ms=self._elapsed_ms(started),
                error_summary=exc.message,
                error_type=type(exc).__name__,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except ProviderError as exc:
            return HealthCheckOutcome(
                status=HealthStatus.UNHEALTHY,
                succeeded=False,
                duration_ms=self._elapsed_ms(started),
                error_summary=exc.message,
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            # An adapter raising something that isn't a ProviderError is a
            # bug in that adapter, but it must not be allowed to break the
            # sweep. Recorded honestly with its real type so the bug is
            # visible in the console rather than disguised as a provider
            # failure.
            return HealthCheckOutcome(
                status=HealthStatus.UNHEALTHY,
                succeeded=False,
                duration_ms=self._elapsed_ms(started),
                error_summary=summarize(exc),
                error_type=type(exc).__name__,
            )

        return HealthCheckOutcome(
            status=HealthStatus.HEALTHY,
            succeeded=True,
            duration_ms=self._elapsed_ms(started),
            detail=detail,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """Monotonic, so a clock adjustment mid-check can't produce a
        negative duration in a latency panel."""
        return int((time.monotonic() - started) * 1000)
