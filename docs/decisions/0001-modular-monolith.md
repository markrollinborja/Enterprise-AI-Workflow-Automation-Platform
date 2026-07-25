# ADR-0001: Modular Monolith Over Microservices

**Status:** Accepted — 2026-07-23

**Context:** The system has several distinct concerns (workflow orchestration, approvals, rules, AI, MCP integrations, notifications, audit). A microservices architecture would give each its own deployable, its own scaling, and clean network boundaries.

**Decision:** Single FastAPI backend with internal service-module boundaries (`services/workflow`, `services/approvals`, etc.), not separate deployable services. Boundaries are enforced by code organization and import discipline, not network calls.

**Alternatives considered:** Full microservices split (one service per concern) — rejected: adds inter-service network calls, service discovery, and distributed-transaction concerns for a system that runs a handful of demo workflows locally. None of that complexity is visible or valuable in a 5-minute demo, and it multiplies the Docker Compose surface area for no functional gain at this scale.

**Consequences:** Easier to run (`docker compose up`, five services total including frontend/db/worker/mcp), easier to reason about transactionally (workflow state changes are single-DB-transaction, not cross-service sagas), easier to explain in an interview. Tradeoff: services can't be scaled or deployed independently — acceptable, since nothing in V1 needs that, and the module boundaries mean a future split is possible without a rewrite if it's ever actually justified.
