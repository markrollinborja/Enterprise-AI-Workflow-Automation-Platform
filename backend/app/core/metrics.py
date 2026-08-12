"""Prometheus metrics (V2 Module 7, observability, part 1 of 3 -- see
docs/architecture/observability.md for the full plan: Loki for logs and
OpenTelemetry/Tempo for traces come next, in that order, once this part is
proven).

Two kinds of metric live here, together, because reading them together is
what actually helps someone operating this platform. **HTTP-level** ones
(request count, latency, by method/route template/status) say whether the
process is healthy. **Domain-level** ones -- workflow throughput by
outcome, approval wait time, MCP integration call latency -- say whether
the *business* the platform automates is actually working. An
infra-only dashboard answers "is the process up," never "is onboarding
completing" -- and the second question is the one Principle 5 asks every
feature to be able to answer in an interview, not just the first.

Uses the default global `prometheus_client` registry, deliberately not a
dedicated `CollectorRegistry` per module and not the library's
multiprocess mode. Every process this module gets imported into -- the
backend's single uvicorn process, the worker's poll loop, each with no
`--workers N` fan-out (see docker-compose.yml) -- runs as exactly one
Python process. Multiprocess mode exists for the case this project never
has: several worker processes behind one exporter needing their samples
merged. Reaching for it anyway would be exactly the overengineering this
project's principles warn against.
"""

from prometheus_client import Counter, Histogram

# --- HTTP (app/main.py's timing middleware feeds these) ---------------------

http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests handled",
    ["method", "route", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
)

# --- Workflow engine (app/services/workflows/service.py) --------------------

workflow_instances_started_total = Counter(
    "workflow_instances_started_total",
    "Workflow instances started -- excludes a dedup-hit return of an "
    "already-existing instance (WorkflowEvent.dedup_key), which is not a "
    "new start",
    ["workflow_key"],
)

workflow_instances_finished_total = Counter(
    "workflow_instances_finished_total",
    "Workflow instances reaching a terminal status",
    ["workflow_key", "status"],
)

# --- Approvals (app/services/approvals/service.py) ---------------------------

approval_decisions_total = Counter(
    "approval_decisions_total",
    "Approval decisions recorded",
    ["approver_role", "decision"],
)

approval_wait_seconds = Histogram(
    "approval_wait_seconds",
    "Time from an approval request's creation to its decision",
    ["approver_role"],
    # Minutes-to-a-day buckets, not the client library's web-latency
    # default (which tops out at 10s) -- a human approval is measured in
    # a completely different order of magnitude than an HTTP request.
    buckets=(30, 60, 300, 900, 1800, 3600, 7200, 21600, 86400, float("inf")),
)

# --- MCP integrations (app/services/integrations/mcp_client.py) -------------

mcp_tool_call_duration_seconds = Histogram(
    "mcp_tool_call_duration_seconds",
    "Duration of a single MCP tool call, success or failure -- count and "
    "sum are exposed automatically per label combination, so this alone "
    "answers both 'how many calls' and 'how long', no separate counter "
    "needed",
    ["tool_name", "caller", "status"],
)
