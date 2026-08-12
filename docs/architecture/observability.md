# Observability

V2 Module 7. Three signals, three parts, built and verified one at a time
— see ADR-0022 for why. **Part 1 (metrics) is done.** Parts 2 and 3 are not
built yet.

| Part | Signal | Stack | Status |
|---|---|---|---|
| 1 | Metrics | Prometheus + Grafana | **Done** |
| 2 | Logs | Loki + Promtail | Not started |
| 3 | Traces | OpenTelemetry + Tempo | Not started |

---

## Part 1: Metrics

### What's instrumented

Two HTTP-level metrics (`app/main.py`'s `metrics_middleware`, every
request through every service that runs one):

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | Counter | `method`, `route`, `status_code` |
| `http_request_duration_seconds` | Histogram | `method`, `route` |

`route` is the matched route *template* (`/employees/{employee_id}`), read
from `request.scope["route"]` after `call_next` resolves it — not the raw
path. A raw-path label would give every distinct employee ID its own time
series, which Prometheus has no way to garbage-collect once created; a
request that never matched a route (a 404 probe) gets the literal string
`"unmatched"` for the same reason.

Four domain-level metrics, each recorded at the point in the service layer
where the event already happens — no separate instrumentation pass, no
event bus:

| Metric | Type | Labels | Recorded in |
|---|---|---|---|
| `workflow_instances_started_total` | Counter | `workflow_key` | `services/workflows/service.py::start_workflow` |
| `workflow_instances_finished_total` | Counter | `workflow_key`, `status` (`completed`/`failed`/`rejected`) | `services/workflows/service.py`, at each terminal transition |
| `approval_decisions_total` | Counter | `approver_role`, `decision` | `services/approvals/service.py::decide` |
| `approval_wait_seconds` | Histogram | `approver_role` | `services/approvals/service.py::decide` |
| `mcp_tool_call_duration_seconds` | Histogram | `tool_name`, `caller`, `status` | `services/integrations/mcp_client.py::call_tool` |

All five are defined together in `app/core/metrics.py` — see that file's
docstring for why HTTP and domain metrics live in one module: reading them
together is what actually helps someone operating this platform answer
both "is the process up" and "is onboarding completing."

`approval_wait_seconds` uses minutes-to-a-day buckets (30s through 24h),
not the client library's web-latency default (which tops out at 10s) — a
human approval is measured in a completely different order of magnitude
than an HTTP request.

### Where /metrics is served

| Process | Port | How |
|---|---|---|
| backend | 8000 (existing) | `GET /metrics` — a normal FastAPI route (`api/routes/metrics.py`) on the same app as everything else |
| mcp_server | 8100 (existing) | `GET /metrics` — mounted via FastMCP's `custom_route` decorator alongside the `/mcp` protocol endpoint on the same ASGI app |
| worker | 9100 (new, `METRICS_PORT`) | `prometheus_client.start_http_server()`, called once before the poll loop starts — the worker has no other HTTP server to piggyback on |

mcp_server exposes baseline process metrics only (Python GC stats, process
memory, etc.) — no per-tool call counters. `mcp_tool_call_duration_seconds`
on the backend side already covers call latency and success/failure from
the calling side, with richer labels (caller, workflow/step context) than
mcp_server could attach to a callee-side counter. See ADR-0022 for the
full reasoning.

### Viewing it

```powershell
docker compose --profile observability up -d
```

Brings up `prometheus` (port 9090) and `grafana` (port 3000, login
`admin` / `admin`) alongside the base stack. Grafana's Prometheus
datasource and the "Meridian Flow - Platform Overview" dashboard are both
provisioned from `infra/observability/` on first boot — no manual setup.

The dashboard (`infra/observability/grafana/provisioning/dashboards/json/meridian-flow.json`)
has seven panels: HTTP request rate by route, HTTP p95 latency by route,
workflow throughput by outcome, approval decision rate by role/outcome,
approval wait time (p50/p95) by role, MCP call duration (p95) by tool, and
MCP call error rate by tool.

To generate data worth looking at: run through the onboarding or access-
request demo scenarios (`docs/architecture/system-architecture.md`'s demo
story) a few times against a `docker compose up` stack with the
`observability` profile also active — every workflow start, approval
decision, and MCP call along the way shows up within one 10s Prometheus
scrape interval.

### What this doesn't cover yet

No alerting rules — Prometheus is scraping and storing, Grafana is
displaying, but nothing pages anyone. Alerting on top of these metrics
(e.g. "approval_wait_seconds p95 > 4h") is a reasonable Part 1.5 addition,
not built in this pass because the module's three-part plan already
allocates the next slice of effort to logs, not alerting depth on top of
metrics.

No metrics retention/storage tuning — Prometheus runs with its defaults
(15 days, local TSDB) via the `prometheus_data` volume. Fine for a
portfolio demo; a real deployment would size retention and consider remote
write to long-term storage.

---

## Part 2 (planned): Logs

Structured JSON logging and correlation IDs already exist (every log line
carries a `correlation_id` — see `app/core/correlation.py` — and
`extra={...}` fields land as queryable top-level JSON keys, not stringified
into the message). What's missing is aggregation: right now those JSON
lines only exist in each container's own stdout, readable via
`docker compose logs`, not searchable across services by correlation ID
in one place. Loki (log aggregation) + Promtail (the shipping agent that
tails each container's stdout and pushes to Loki) fill that gap, added to
Grafana as a second datasource so a correlation ID pasted into Grafana's
Explore view finds every log line across backend, worker, and mcp_server
for one transaction — the same "one string, one transaction" property
`app/main.py`'s correlation-ID middleware docstring already describes for
n8n and the support console (Module 8).

## Part 3 (planned): Traces

OpenTelemetry instrumentation + Tempo (trace storage), tied into the
existing correlation ID so a trace and its log lines share one identifier.
Deliberately last: a trace answers "where did the time go inside one
request," which is the most detailed and most expensive-to-build signal of
the three, and the least useful to build first on a platform whose
workflow steps are already individually timed and audited via
`WorkflowStepInstance` rows and `MCPToolExecution` rows. Metrics said
whether something's wrong; logs will say what happened; traces will say
exactly where inside the request it happened — worth having, but only
once the first two signals are proven.
