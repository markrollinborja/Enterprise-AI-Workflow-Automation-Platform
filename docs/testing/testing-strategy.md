# Testing Strategy

Phase 14 checkpoint. Written after auditing the suite that had already accumulated incrementally since Phase 3 — the honest finding was that domain coverage was already strong (every phase's own checkpoint added its own tests as it went, per this project's phase-by-phase discipline), but two real gaps existed in the *infrastructure* around that coverage: `mcp_server`'s tests never ran in CI, and there was no coverage number to cite. This doc records what's covered, what isn't, and why — not a plan for tests still to be written.

## What's covered, and where

**Unit tests** (pure functions, no DB, no I/O): `services/workflows/state_machine.py` (`test_state_machine.py` — every entry in both transition tables exercised as an allowed-transition test, plus a representative sample of disallowed ones, including every terminal state), `services/workflows/conditions.py` (`test_conditions.py` — the safe `ast`-based condition parser, including explicit malicious-expression rejection tests), `services/rules/service.py` (`test_rules.py` — the full risk-classification matrix).

**Integration tests** (real Postgres via `db_session`, no mocked repositories): the workflow engine end-to-end (`test_workflow_engine.py` — happy path, rejection, retry-and-recover, retries-exhausted, `continue`-behavior failures, idempotency on `dedup_key`, worker polling via `poll_once`, the Phase 13 advisory-lock contention case, and manual retry including the completed-instance edge case), the approval engine (`test_approvals.py` — approver resolution, inbox filtering by role/assignment/pool, approve/reject, authorization, already-decided conflicts), the access-request flow (`test_access_requests.py` — auto-approve, high-risk multi-approver pause, missing-employee-link, unknown-application, full HTTP round trip), the AI service (`test_ai_service.py` — confidence-based review routing, graceful fallback on missing key/no catalog/model refusal, the dynamic catalog constraint, agentic tool-calling, the Phase 13 timeout wiring), the MCP client (`test_mcp_client.py` — configured timeout reaching the transport, failure-row recording on timeout), the Jira fulfillment webhook (`test_jira_webhook.py` — signature verification, idempotency, unknown/non-Done deliveries), the notification system (`test_notifications.py` — in-app/Slack/email writes, Slack-failure resilience, no-recipient no-op, engine wiring at all three trigger points), and the dashboard/audit/retry surface (`test_dashboard.py` — summary aggregates, instance list filtering, instance detail composition, the composed audit timeline both globally and per-instance, admin-only route gating across every route, and the Phase 13b retry endpoint).

**Permission tests**: every Administrator-only route family (`dashboard`, `workflow-instances`, `audit-log`, `retry`) asserts a 403 for a non-admin and for an unauthenticated caller; `test_employees.py` and `test_access_requests.py` cover role restrictions on their own routes the same way.

**AI mock tests**: `test_ai_service.py` mocks the OpenAI client at the `_client()` boundary — no real network call, no API key, and no non-determinism anywhere in the suite.

**MCP mock tests**: `conftest.py`'s autouse fixture mocks `_call_tool_async` for every backend test that exercises an `mcp_tool` step; `mcp_server/tests/` tests the tool implementations themselves directly (`test_jira_tool.py`, `test_slack_tool.py`, `test_calendar_tool.py` — all mock-mode, no real credentials; `test_employee_tool.py` is the one exception — `lookup_employee` has no mock mode, so those tests hit a real, migrated Postgres, seeding and cleaning up their own rows rather than depending on `backend/`'s seed data).

**Failure-path tests**: covered throughout the integration tests above rather than as a separate suite — every write path's failure mode is exercised alongside its success mode in the same file (retry-and-recover and retries-exhausted live next to the happy path in `test_workflow_engine.py`, Slack-failure resilience lives next to successful sends in `test_notifications.py`, and so on) — this was a deliberate choice from early phases, not a gap: a failure test that doesn't sit next to the success case it's a variant of is easy to let drift out of sync with it.

## What Phase 14 actually added

1. **`mcp_server` in CI.** Its four test files existed and passed locally since Phase 10, but `.github/workflows/ci.yml` only ever had `backend` and `frontend` jobs — `mcp_server`'s tests never ran automatically on a push or PR. Added a third job, mirroring `backend`'s Postgres-service setup (needed for `test_employee_tool.py`'s real-DB tests) and running backend's own `alembic upgrade head` first, since `mcp_server` never owns migrations itself (see `app/db.py`'s docstring, ADR-0005).
2. **`pytest-cov` in both Python suites.** `backend` and `mcp_server`'s CI steps now run with `--cov=app --cov-report=term-missing`, so there's a real, current number in every CI log instead of a qualitative "we have tests" claim. No enforced minimum threshold (`--cov-fail-under`) — a hard gate is easy to either make meaningless (set low enough to never trip) or actively harmful (blocks a legitimate PR over an arbitrary number on a project this size); the number itself, visible in every run, is the useful signal.

## Current numbers

From a local run (`pytest --cov=app --cov-report=term-missing`), 2026-07-30: **backend 192 tests passing, 90% statement coverage**; **mcp_server 9 tests passing, 72% statement coverage**. mcp_server's lower number isn't a gap — `--cov-report=term-missing` shows the uncovered lines are almost entirely the real-mode branches of `app/tools/{jira,slack,calendar}.py` (need live credentials, deliberately never exercised in CI, matching `MCP_MOCK_MODE=true`'s default) and `app/server.py`'s FastMCP tool-registration wiring (exercised in practice by `docker compose up`, not worth a dedicated test for what's essentially framework glue). Backend's own uncovered lines are dominated by `app/db/seed.py` (0% — a startup script, not application logic under test) and a handful of defensive `if x is None: raise` branches in repositories that no test deliberately triggers.

## What's deliberately not covered

**Frontend component/unit tests.** No Vitest, no React Testing Library, no test files anywhere under `frontend/src/`. Considered and cut, not overlooked: the React surface here is a handful of admin dashboard pages and one approval-inbox form, each a thin fetch-and-render wrapper over already-integration-tested backend endpoints — the business logic worth protecting with tests (state transitions, approval routing, retry semantics, risk classification) all lives server-side and is exercised there. Standing up a frontend test framework to assert that a status badge renders the right CSS class would cost real setup time for coverage of presentation logic, not the domain logic this project's target roles (Automation/Backend/AI Agent/Integration Engineer) actually get evaluated on. `frontend`'s CI job still runs `eslint` and a real `npm run build` on every push, which catches the failure mode that would actually matter (a broken build, a type error) without needing a test framework to do it.

**Browser-driven end-to-end tests** (Playwright/Cypress driving the actual UI). The route-level tests in `test_dashboard.py`, `test_approvals.py`, etc. already exercise full HTTP request → auth → service → DB → response round trips via FastAPI's `TestClient`, which is genuine end-to-end coverage of everything except pixels on screen. A real browser E2E suite is a reasonable Version 2 addition if this project ever needs regression protection on the frontend's actual rendering, not something V1's scope calls for (see the project's own non-goals list — this project already deliberately keeps frontend scope thin).

## Running everything locally

```powershell
# backend — requires migrations applied against a reachable Postgres
cd backend
pytest -v --cov=app --cov-report=term-missing
ruff check .
mypy app

# mcp_server — the non-DB tests (jira/slack/calendar tools) always work;
# test_employee_tool.py additionally needs the same migrated Postgres
cd ../mcp_server
pytest -v --cov=app --cov-report=term-missing
ruff check .
mypy app

# frontend
cd ../frontend
npm run lint
npx tsc -b
npm run build
```
