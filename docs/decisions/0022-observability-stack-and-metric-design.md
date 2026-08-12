# ADR-0022: Observability Stack and Metric Design (Module 7, Part 1)

**Status:** Accepted — 2026-08-11

**Context:** V2 Module 7 asks for OpenTelemetry, Prometheus, Loki, Tempo,
and Grafana — full metrics/logs/traces observability. Structured JSON
logging and correlation IDs already exist (Phase 7 of Module 1, ADR before
this one); what's missing is metrics and traces. Building all three
signals at once, and every service's instrumentation, in one pass risks
the same mistake this project's principles warn against elsewhere: a wide,
shallow feature nobody can talk through in an interview. The module is
split into three parts instead — metrics (this ADR), then logs
aggregation (Loki), then traces (OpenTelemetry/Tempo) — each shipped and
verified before the next starts, matching how Module 4 (Identity) shipped
OIDC completely before starting the SAML PoC.

Two design questions needed answers before writing code: what actually
gets instrumented (infra-only vs. domain metrics), and how to expose them
without breaking the existing dependency pin.

**Decision:**

*Domain metrics, not just infra metrics.* Request count and latency
(`http_requests_total`, `http_request_duration_seconds`) answer "is the
process up" — necessary, but not what Principle 5 asks every feature to
answer in an interview. Four more metrics answer "is the business the
platform automates actually working": `workflow_instances_started_total` /
`workflow_instances_finished_total` (throughput by outcome — completed vs.
failed vs. rejected), `approval_decisions_total` / `approval_wait_seconds`
(is the human-in-the-loop step a bottleneck), and
`mcp_tool_call_duration_seconds` (integration latency and error rate, by
tool). All five live in one module, `app/core/metrics.py`, read together —
see that module's own docstring for why splitting HTTP and domain metrics
into separate files would work against the actual point of the dashboard.

*Hand-rolled HTTP-timing middleware, not `prometheus-fastapi-instrumentator`.*
That library is the obvious first choice for FastAPI metrics, and it was
tried first. `pip install prometheus-fastapi-instrumentator` in a clean
venv pulled in `starlette>=1.0`, which breaks this project's
`fastapi==0.115.6` pin (`starlette<0.42.0,>=0.40.0` per FastAPI's own
dependency spec) — confirmed empirically, not assumed, by installing it and
watching pip's own resolver warning, then uninstalling both packages and
reinstalling the pinned `starlette`/`fastapi` pair to restore a working
environment. A `@app.middleware("http")` function mirroring the existing
correlation-ID middleware's shape (`app/main.py`) records the same two
metrics in about fifteen lines, with no new dependency and no version
coupling to a library maintained faster than this project's own FastAPI
pin moves.

*Default global registry, not multiprocess mode.* `prometheus_client`
supports a multiprocess mode for the case where several worker processes
behind one exporter need their samples merged (e.g. `gunicorn -w 4`). Every
process this module runs in — backend's single uvicorn process, the
worker's poll loop, mcp_server's single FastMCP process — is exactly one
Python process (see `docker-compose.yml`: no `--workers N` anywhere).
Reaching for multiprocess mode anyway would be instrumentation solving a
scaling problem this deployment doesn't have.

*Worker gets its own metrics port; backend and mcp_server ride their
existing HTTP servers.* `api/routes/metrics.py` mounts `/metrics` on the
FastAPI app already serving the rest of backend's routes — no new port.
`mcp_server/app/server.py` does the same via FastMCP's `custom_route`
decorator, confirmed via `inspect.getsource` against the installed
`mcp==1.9.4` SDK that this decorator exists and mounts an arbitrary
Starlette route alongside the `/mcp` protocol endpoint on the same ASGI
app — same version-drift caution as `mcp_client.py`'s
`streamablehttp_client` import note, since this SDK has already changed
shape release to release once in this project's history. `app/workers/runner.py`
has no HTTP server at all — its poll loop is the entire process — so
`prometheus_client.start_http_server(settings.metrics_port)` opens one
just for this, once, before the poll loop starts. `METRICS_PORT=9100`
follows the node-exporter-family convention for "a process's own metrics
port."

*mcp_server exposes baseline process metrics only — no per-tool call
counters.* `backend/app/services/integrations/mcp_client.py`'s
`mcp_tool_call_duration_seconds` already records every call's duration,
tool name, caller, and success/failure from the calling side — the
richer vantage point, since it also has `workflow_instance_id` /
`step_instance_id` context available to correlate against. Duplicating a
second counter inside mcp_server itself would double-count the same event
from the callee's side for no additional signal; it would exist only to
make the mcp_server dashboard panel technically self-contained, not
because it answers a question the backend-side metric doesn't already
answer.

*Grafana dashboards provisioned as code, as a single mount.*
`infra/observability/grafana/provisioning/` — datasource YAML, the
dashboard-loader YAML, and the dashboard JSON itself
(`provisioning/dashboards/json/meridian-flow.json`) — is checked into the
repo and mounted read-only as one bind mount, the same pattern this
project already uses for `infra/keycloak/realm-meridian.json`. The
dashboard JSON originally lived in a sibling directory
(`infra/observability/grafana/dashboards/`) mounted as a *second*, nested
bind mount inside the first — that broke on Docker Desktop for Windows
(WSL2) with "read-only file system" at container create, because Docker
can't create a mountpoint for a second bind mount inside a directory the
first mount already made read-only. Found running this for real, not by
inspection; moving the dashboard JSON inside `provisioning/` itself
collapses it to one mount and the nesting problem disappears. Someone
running `docker compose --profile observability up` gets a working
dashboard on first boot, not an empty Grafana that needs to be clicked
together by hand and is lost the moment the `grafana_data` volume is
removed.

**Alternatives considered:**

*Infra-only metrics (HTTP request count/latency, nothing domain-specific)*
— rejected per the "domain metrics" reasoning above: it demonstrates
"knows how to add a `/metrics` endpoint," not "understands what a
business-process automation platform should be measured by," which is the
weaker interview story.

*`prometheus-fastapi-instrumentator`* — rejected per the dependency
conflict found empirically above. Noted here because it's the first
result for "FastAPI Prometheus metrics" and a reviewer would reasonably
ask why this project didn't use it.

*Multiprocess `CollectorRegistry` mode* — rejected per the "default global
registry" reasoning above: solves a fan-out problem this single-process
deployment doesn't have.

*A shared metrics port across backend and worker (e.g. both on 8000)* —
not possible: they're two separate OS processes in two separate
containers, each needs its own bound port regardless of which one "feels"
like the primary process.

**Consequences:**

Adding a sixth domain metric later (e.g. AI service confidence-threshold
outcomes, once traces make it obvious that's the next question worth
asking) means adding one `Counter`/`Histogram` to `metrics.py` and one
`.inc()`/`.observe()` call at the point the event already happens in the
service layer that owns it — no new wiring pattern to invent, matching how
`approval_decisions_total` and `mcp_tool_call_duration_seconds` were added
to the same file without disturbing `http_requests_total`.

The Prometheus/Grafana services live behind the `observability` compose
profile (`docker-compose.yml`), not the base stack — someone who just
cloned this repo runs `docker compose up` and gets the V1 five-service
platform with no additional containers they did not ask for, matching the
`identity` and `integrations` profiles' precedent.

Parts 2 (Loki) and 3 (OpenTelemetry/Tempo) are not built yet — see
`docs/architecture/observability.md` for what's deferred and why doing
metrics first was the right order (a metric answers "is something wrong,"
logs and traces answer "why," and the second question is only useful once
the first one is instrumented).
