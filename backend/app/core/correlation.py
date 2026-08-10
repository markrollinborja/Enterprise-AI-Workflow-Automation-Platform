"""Correlation IDs — the single thread that ties one business transaction
together across every log line, database row, provider call, and trace.

Why this exists (Phase 1, v2): a v1 failure was debuggable by opening one
workflow instance and reading its steps, because everything happened inside
this process. In v2 a single customer onboarding crosses Salesforce, n8n,
this API, SCIM, Keycloak, and Microsoft Graph. "Which Slack alert, which n8n
execution, which workflow instance, and which Graph 403 were all the *same*
transaction?" is unanswerable without one identifier that every hop
preserves. That identifier is generated at the true edge (Salesforce ->
n8n), passed inward on the `X-Correlation-ID` header, and echoed back on the
response so callers can log what they were told.

Deliberately a ContextVar, not a parameter threaded through every function:
this value has to reach logging — which no call site passes arguments to —
and every service already has a deep call stack. ContextVar is the standard
mechanism for exactly this, and it is asyncio-task-safe (each task inherits a
copy at creation, so concurrent requests can't read each other's value).

Note the distinction from a trace ID (Module 7, OpenTelemetry): a trace ID is
generated per trace by the tracing SDK and is meaningless outside a trace
backend. A correlation ID is business-level, supplied by the caller, stored
in our own tables, and searchable in the support console by a human reading
it out of a Slack message. They coexist; they are not substitutes.
"""

import uuid
from contextvars import ContextVar

# The header this app reads inbound and writes outbound. n8n sets it when it
# normalizes a Salesforce event (Module 3); anything calling us without it
# gets one generated, so a correlation ID always exists rather than being
# conditionally present — code downstream never has to handle None.
CORRELATION_ID_HEADER = "X-Correlation-ID"

# Default "-" rather than None so log formatting never has to special-case a
# missing value. Any log line emitted outside a request or worker cycle
# (import time, startup) shows "-" instead of crashing the formatter or
# printing "None", which reads like a bug in the correlation plumbing.
_UNSET = "-"

# Wide enough for a prefixed UUID (39 chars), a Salesforce request ID, or an
# n8n execution ID, and narrow enough that the matching database column stays
# indexable and a log line stays readable.
MAX_CORRELATION_ID_LENGTH = 128

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default=_UNSET)


def new_correlation_id() -> str:
    """Generate a fresh correlation ID.

    Prefixed so a human eyeballing a Slack alert, a Jira ticket, and a log
    line can tell at a glance that the string is one of ours and not a Jira
    issue key, a Salesforce 18-character ID, or an OpenTelemetry trace ID.
    """
    return f"mf-{uuid.uuid4()}"


def get_correlation_id() -> str:
    """The correlation ID for the current request/task, or "-" if unset."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID to the current context.

    Callers outside HTTP — the background worker starting a workflow cycle,
    a test, an n8n-triggered replay — call this directly. Inside HTTP the
    middleware does it. There is intentionally no "clear": ContextVar
    values are scoped to the task, and both the middleware and the worker
    set a fresh value at the start of every unit of work, so a stale ID
    cannot leak into the next one.
    """
    _correlation_id.set(correlation_id)


def ensure_correlation_id(candidate: str | None) -> str:
    """Return `candidate` if it is a usable correlation ID, else a new one.

    Inbound values are untrusted: they land in logs, in database columns,
    and in the support console's search box. An unbounded or newline-bearing
    string would let a caller forge fake log lines (log injection) or blow
    past the column width. Anything failing those checks is replaced rather
    than rejected — a malformed correlation ID is not a reason to fail an
    otherwise valid business request, it just means we mint our own and the
    caller loses the ability to correlate on their side.
    """
    if candidate is None:
        return new_correlation_id()
    candidate = candidate.strip()
    if not candidate or len(candidate) > MAX_CORRELATION_ID_LENGTH:
        return new_correlation_id()
    if not all(c.isalnum() or c in "-_:." for c in candidate):
        return new_correlation_id()
    return candidate
