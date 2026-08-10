"""Provider failure taxonomy and secret redaction.

Two jobs, deliberately in one module because they are always used together:
classifying *why* an external provider call failed, and making the resulting
evidence safe to store and show.

**Why a taxonomy at all.** V1 had one integration surface (MCP) and one
failure question: did the step work? V2 talks to Salesforce, Keycloak, SCIM
clients, Microsoft Graph, Jira, Slack, and n8n, and the only question that
matters operationally is *"is retrying this going to help?"* Retrying a 429
is correct and will succeed. Retrying a 403 "missing object permission" will
fail identically forever while burning the retry budget, delaying the real
escalation, and filling the support console with noise. That distinction —
transient versus permanent — is the single most important piece of
information a failed provider call carries, so it is modelled in the type
system rather than re-derived by string-matching error messages at each call
site.

**Why redaction lives here.** Provider errors are the most likely place for a
secret to leak into somewhere permanent. A real Salesforce 401 body can echo
the bearer token; a misconfigured request can put an API key in a URL query
string; an exception's repr can carry the whole request object. Those strings
end up in three durable places — logs, the `last_error_summary` column, and
the support console — so redaction is applied at construction time, not
hopefully remembered at each of those three sinks.
"""

import re
from typing import Any

from app.core.exceptions import AppError

# Substrings that mark a mapping key as carrying a secret. Matched
# case-insensitively against the *key*, not the value: guessing at values
# ("does this look like a token?") produces both false negatives on
# short-lived opaque strings and false positives on ordinary text. Keys are
# stable and few.
_SECRET_KEY_MARKERS = (
    "authorization",
    "auth",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "refresh_token",
    "access_token",
    "id_token",
    "session",
    "cookie",
    "signature",
    "assertion",
)

_REDACTED = "[REDACTED]"

# Free-text patterns, for the case where a secret is embedded in a message
# rather than sitting in its own field — which is exactly what a provider's
# error body does. Ordered most-specific first; each is applied to every
# string that gets persisted or logged.
_SECRET_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Authorization: Bearer eyJ..." / "authorization=Bearer abc"
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"),
    # key=value or "key": "value" for any sensitive-looking key
    re.compile(
        r"(?i)\b(" + "|".join(_SECRET_KEY_MARKERS) + r")"
        r"[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9\-._~+/=]{6,})"
    ),
    # Bare JWTs — three base64url segments separated by dots. Salesforce,
    # Keycloak and Graph all hand these back inside error payloads.
    re.compile(r"\beyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}"),
    # Slack tokens have a recognizable, documented prefix shape.
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
)

# Persisted provider error summaries are for a human triaging in the support
# console, not for forensic reconstruction of a provider's entire response.
# Bounded so one pathological HTML error page can't bloat every row of the
# connections table.
MAX_ERROR_SUMMARY_LENGTH = 500


def redact_text(value: str) -> str:
    """Strip anything that looks like a credential out of free text.

    Applied to every provider error message before it is logged or stored.
    Conservative by construction: it can over-redact (an innocent field named
    `session_name` loses its value) and that is the correct direction to fail.
    """
    redacted = value
    for pattern in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact secret-looking keys in a payload.

    For request/response bodies persisted as evidence (webhook deliveries,
    provider call records). Values under a secret-looking key are replaced
    wholesale; every other string value still goes through `redact_text`,
    because a secret can hide inside an innocently-named field.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if any(marker in key.lower() for marker in _SECRET_KEY_MARKERS):
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = redact_mapping(value)
        elif isinstance(value, list):
            result[key] = [
                redact_mapping(item)
                if isinstance(item, dict)
                else redact_text(item)
                if isinstance(item, str)
                else item
                for item in value
            ]
        elif isinstance(value, str):
            result[key] = redact_text(value)
        else:
            result[key] = value
    return result


class ProviderError(AppError):
    """Base class for every external provider failure.

    Subclasses `AppError` so that if one ever escapes to a route it produces
    the same consistent JSON shape as every other error rather than a bare
    500 — but nothing in the domain layer should be *catching* it as an
    AppError. The interesting question is always transient-vs-permanent, and
    that is answered by `is_retryable`, not by the HTTP status.

    502 rather than 500: the failure is in an upstream dependency, not in
    this application. That distinction matters when reading a dashboard —
    a spike of 502s points at a provider, a spike of 500s points at us.
    """

    status_code = 502

    #: Whether the workflow engine should schedule another attempt. The
    #: single most consequential attribute in this module.
    is_retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        operation: str | None = None,
        status_code_from_provider: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        # Redacted here, at construction, so no call site can accidentally
        # persist or log the raw message — there is no path to the unredacted
        # string once the exception exists.
        super().__init__(redact_text(message)[:MAX_ERROR_SUMMARY_LENGTH])
        self.provider = provider
        self.operation = operation
        self.status_code_from_provider = status_code_from_provider
        self.retry_after_seconds = retry_after_seconds

    def log_context(self) -> dict[str, Any]:
        """Fields to pass as `extra={...}` when logging this failure.

        Keeps every provider failure log line shaped identically, which is
        what makes "error rate by provider and operation" a Grafana query
        (Module 7) instead of a regex over message text.
        """
        return {
            "provider": self.provider,
            "operation": self.operation,
            "error_type": type(self).__name__,
            "retryable": self.is_retryable,
            "provider_status": self.status_code_from_provider,
        }


class TransientProviderError(ProviderError):
    """The call failed for a reason that may not recur — retry is worthwhile.

    Network timeouts, connection resets, provider 5xx, and anything else
    where the same request later has a genuine chance of succeeding.
    """

    is_retryable = True


class PermanentProviderError(ProviderError):
    """The call will fail identically until something changes — do not retry.

    Bad request shape, unknown field, missing permission, not found. These
    need a human or a configuration change, so they should escalate
    immediately rather than consume the retry budget first.
    """

    is_retryable = False


class ProviderRateLimitError(TransientProviderError):
    """429, or a provider-specific quota signal.

    Retryable, but only after waiting. `retry_after_seconds` carries the
    provider's own guidance (Salesforce and Graph both send it) so backoff
    can honour it instead of guessing — ignoring a documented Retry-After is
    how a rate limit turns into a temporary ban.
    """


class ProviderAuthError(ProviderError):
    """Authentication or authorization failed (401/403).

    Deliberately not a subclass of either transient or permanent, because
    this one genuinely depends: an *expired* access token is transient — a
    refresh fixes it and the retry succeeds. A *revoked* credential or a
    missing OAuth scope is permanent and no amount of retrying helps.

    `refreshable` carries that distinction, and `is_retryable` derives from
    it, so callers keep asking the same single question.
    """

    def __init__(self, message: str, *, refreshable: bool = False, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.refreshable = refreshable
        self.is_retryable = refreshable


class ProviderConfigurationError(PermanentProviderError):
    """The connection is not usable as configured — missing base URL, absent
    credentials, unknown provider type.

    Separated from other permanent failures because the remedy is different
    and the support console should say so: this is not "the provider broke",
    it is "this connection was never set up correctly", and no retry or
    escalation to the provider will help.
    """


class ProviderTimeoutError(TransientProviderError):
    """The provider did not respond inside our own deadline.

    Its own class rather than a generic transient error because a timeout is
    the one failure where the request may well have *succeeded* on the
    provider's side — which is exactly when idempotency keys matter. Callers
    that create resources must treat this as "unknown outcome", not "failed".
    """


# Provider HTTP status -> our classification. Anything not listed falls back
# to transient for 5xx and permanent for everything else, on the reasoning
# that an unrecognized server-side failure is worth one more attempt while an
# unrecognized client-side failure is our bug and will not fix itself.
_STATUS_MAP: dict[int, type[ProviderError]] = {
    400: PermanentProviderError,
    404: PermanentProviderError,
    405: PermanentProviderError,
    409: PermanentProviderError,
    422: PermanentProviderError,
    408: ProviderTimeoutError,
    429: ProviderRateLimitError,
    500: TransientProviderError,
    502: TransientProviderError,
    503: TransientProviderError,
    504: ProviderTimeoutError,
}


def classify_status(status: int) -> type[ProviderError]:
    """Map a provider HTTP status onto the right error class.

    401/403 are absent from `_STATUS_MAP` on purpose: choosing between
    refreshable and non-refreshable needs provider-specific knowledge (is
    this an expired token or a revoked grant?), which belongs in that
    provider's adapter, not in a generic status table. Adapters raise
    `ProviderAuthError` themselves with `refreshable` set.
    """
    if status in _STATUS_MAP:
        return _STATUS_MAP[status]
    if status in (401, 403):
        return ProviderAuthError
    return TransientProviderError if status >= 500 else PermanentProviderError


def summarize(exc: BaseException) -> str:
    """A short, redacted, human-readable description of any failure.

    Used for `IntegrationConnection.last_error_summary` and for the support
    console. Accepts `BaseException` rather than `ProviderError` because the
    thing that killed a provider call is frequently not one of ours — an
    httpx timeout, a JSON decode error, an `ExceptionGroup` from an async
    teardown — and the console still has to render something honest.
    """
    text = f"{type(exc).__name__}: {exc}"
    return redact_text(text)[:MAX_ERROR_SUMMARY_LENGTH]
