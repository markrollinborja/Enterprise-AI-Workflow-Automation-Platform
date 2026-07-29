# ADR-0002: DB-Backed Workflow Engine + Polling Worker, No Broker

**Status:** Accepted — 2026-07-23

**Context:** Workflow steps need to execute asynchronously, support retry with backoff, and pause/resume across human approvals that may take minutes to hours. Common solutions: a message-broker-backed task queue (Celery/RQ + Redis), a dedicated workflow orchestrator (Temporal), or a database-backed job table with a polling worker.

**Decision:** Postgres is both the workflow state store and the job queue. A separate worker process polls for due `WorkflowStepInstance` rows and executes them through the same service-layer code the API uses.

**Alternatives considered:** Celery/RQ + Redis — rejected for V1: adds a broker as a sixth moving part and its own failure modes, for throughput this project will never approach. Temporal — genuinely the "right" tool for pausable/resumable workflows at real scale, but too much infrastructure to justify for a solo V1; documented as the explicit upgrade path if this needed production throughput.

**Consequences:** State and queue can never disagree (same DB, same transaction boundary) — a class of bug broker-based systems have to specifically guard against. Tradeoff: polling latency (2-5s) instead of push-based dispatch, and no built-in horizontal fan-out — both acceptable at demo scale. Locking a candidate instance while it's being advanced turned out to need a Postgres session-level advisory lock, not `SELECT ... FOR UPDATE` as originally assumed here — see [ADR-0013](./0013-advisory-lock-for-workflow-advancement.md) for why, and for what that means for adding worker replicas later.

**See also:** [background-jobs.md](../architecture/background-jobs.md)
