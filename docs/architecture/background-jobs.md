# Background Job / Async Execution Approach

## Approach: DB-backed polling worker, no broker

A separate process (`python -m app.workers.runner`, its own Docker Compose service, same codebase and database as the API) polls `WorkflowStepInstance` for rows where `status = pending` and `scheduled_at <= now()`, claims them (a `SELECT ... FOR UPDATE SKIP LOCKED` or equivalent row lock to avoid two worker instances double-processing the same step — relevant even at 1 worker replica, since it's still correct and cheap to write it that way), and calls the same `services/workflow` execution code the API would call. The worker is a scheduler, not a second implementation of workflow logic.

Retries are just another row in `pending` with `scheduled_at` set to `now() + backoff(attempt_count)` — no separate retry-queue concept needed.

## Why not Celery/Redis/RQ/Temporal

Evaluated against the actual requirement — reliable execution of a handful of concurrent demo workflows, with retries and pause/resume — not against a hypothetical production load:

- **Celery/RQ** need Redis (or another broker) running as a sixth service, plus broker-specific failure modes (lost messages, worker-broker connection handling) that don't teach anything this project needs to demonstrate. They'd be justified if the project needed high-throughput fan-out or distributed workers across machines — it doesn't.
- **Temporal** is a genuinely good fit for exactly this kind of "long-running, pausable, resumable workflow" problem, but it's a significant piece of infrastructure (its own server, its own SDK model) for a solo portfolio project's V1. Worth naming as a "if this had to scale to real production throughput, here's the upgrade path" talking point — not worth building now.
- A **DB-backed job model** is the simplest thing that actually demonstrates the concepts under test (reliable async execution, retry with backoff, pause/resume, idempotency) without a new infrastructure dependency. Postgres is already the source of truth for workflow state, so using it as the job queue too means state and queue can never disagree with each other — a class of bug broker-based systems have to work to avoid.

## Poll interval and staleness

Worker polls every 2-5 seconds (configurable). For a system where "time to next step" isn't sub-second-critical (these are human-approval-gated business workflows, not a trading system), this is an acceptable latency tradeoff for the simplicity gained. Documented explicitly so it doesn't read as an oversight.

## What this doesn't handle (and doesn't need to for V1)

Horizontal worker scaling beyond one replica isn't needed at demo scale, but the row-locking approach above means adding a second worker replica later wouldn't require a redesign — worth knowing the answer to "how would this scale" without having built it.

## Update (Phase 6): built, with one deliberate simplification

`app/workers/runner.py` is real — a Docker Compose service polling every 3 seconds via `workflow_instance_repo.list_ready_to_advance()`, calling `services/workflows/service.py::advance_workflow()` on each result. That function is also called synchronously right after `start_workflow` and `resume_workflow_step` — so a demo doesn't wait on a poll tick for steps that resolve immediately; the worker's real job is picking up retry-scheduled steps once their backoff has elapsed.

**Simplification taken at the time:** no locking yet — `list_ready_to_advance` was a plain read, deferred to Phase 13. This turned out to matter well before a second worker replica ever existed: the single worker's poll and an API request's own inline `advance_workflow` call could both grab the *same* instance, since nothing serialized them against each other. See the Phase 13 update below for what actually closed that gap.

## Update (Phase 13): the locking ADR-0002 anticipated, built — as an advisory lock, not `FOR UPDATE`

The race wasn't hypothetical: it surfaced as a real `InvalidTransitionError: Cannot transition from 'running' to 'running'` the first time a manual test happened to hit the timing window (an approval decided while the worker's next poll tick landed on the same instance). ADR-0002 assumed `SELECT ... FOR UPDATE SKIP LOCKED` would be the fix. It wasn't — `advance_workflow`'s loop commits after every step transition (deliberately, for durability: a crash mid-loop keeps whatever committed before it), and a row lock from `FOR UPDATE` releases at the very first of those commits, not at the end of the call. That's exactly the gap a step sitting `RUNNING` while an OpenAI or MCP call is in flight falls into.

The actual fix (see [ADR-0013](../decisions/0013-advisory-lock-for-workflow-advancement.md)): a Postgres session-level advisory lock, keyed by `hashtext(instance_id::text)`, held for the whole `advance_workflow` call regardless of how many commits happen inside it — the right primitive for a critical section that spans multiple transactions. `advance_workflow` (every synchronous caller: `start_workflow`, `resume_workflow_step`, `confirm_external_completion`) blocks until it acquires the lock; `try_advance_workflow` (the worker's poll loop only) tries non-blockingly and skips the instance for this tick if another caller already holds it — the next 3-second tick just retries, which is fine, since the worker was always meant to be a scheduler that can afford to skip a beat, not the only path that advances a workflow.

Also added this phase: explicit timeouts on the OpenAI (`Settings.openai_timeout_seconds`, default 20s — the SDK's own default is 600s) and MCP (`Settings.mcp_call_timeout_seconds`, default 10s — the SDK's own default is 30s) client calls, so a hung external call fails fast enough to actually reach the retry/backoff window described above instead of stalling a poll cycle indefinitely.
