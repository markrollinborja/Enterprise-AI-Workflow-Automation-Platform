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

**Simplification taken:** no `SELECT ... FOR UPDATE SKIP LOCKED` yet — `list_ready_to_advance` is a plain read. At one worker replica this is correct (nothing else could be claiming the same row concurrently); it's deferred to Phase 13 (Reliability) rather than built speculatively now, since it has no test that could prove it matters without a second replica to race against. Flagged here explicitly rather than silently skipped, since ADR-0002 called it out as "cheap to write regardless."
