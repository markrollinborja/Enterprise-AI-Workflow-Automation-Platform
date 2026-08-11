# Meridian Flow — Agent Guide

Enterprise workflow orchestration platform. V1 automates employee operations
(onboarding, software access requests). V2 extends it into an enterprise
identity, integration and support-reliability platform.

**One repository, one portfolio project.** Multiple services and containers are
fine; separate projects are not.

---

## Current state

- Protected baseline: tag `v1.0-workflow-platform` (commit `b514f2b`)
- Active branch: `feature/enterprise-integration-reliability`
- V1 is complete and green: 202 tests (193 backend, 9 mcp_server), ruff + mypy
  clean, ESLint clean, production frontend build succeeds
- V2 is in progress. See `docs/decisions/` for every architectural decision.

**Never break the baseline.** If a change makes existing tests fail, fix the
change — do not edit the test to match new behavior unless the behavior change
is intentional, and say so explicitly when it is.

---

## Layout

```
backend/          FastAPI app, domain logic, workflow engine   (Python 3.12)
  app/api/routes/   HTTP layer only — no business logic
  app/services/     business logic, one package per domain
  app/repositories/ database access, one module per aggregate
  app/models/       SQLAlchemy models
  app/schemas/      Pydantic request/response schemas
  app/core/         config, logging, security, correlation, exceptions
  app/workers/      background poll-loop runner
  alembic/versions/ migrations, numbered 0001..NNNN
frontend/         React + TypeScript + Vite + Tailwind + shadcn/ui
mcp_server/       separate FastMCP service (Jira, Slack, Calendar tools)
workflows/        JSON workflow definitions (config, not code — ADR-0003)
docs/             architecture, decisions (ADRs), api, security, testing
```

---

## Commands

Run backend commands from `backend/`, frontend from `frontend/`.

```bash
# Backend
ruff check .                 # lint — must pass
mypy app                     # type check — must pass
alembic upgrade head         # apply migrations
pytest -q                    # full suite
pytest tests/test_x.py -vv   # single file

# Frontend
npm run lint                 # ESLint
npm run build                # tsc -b && vite build

# Full stack
docker compose up            # db, backend, worker, mcp_server, frontend
```

Backend tests need PostgreSQL reachable via `DATABASE_URL` and a
`JWT_SECRET_KEY`. They do **not** need Docker, Keycloak, or any external
provider — keep it that way. A test suite that requires containers is a test
suite that stops getting run.

`DATABASE_URL` for tests must point at a database that has migrations
applied and has **never** run `python -m app.db.seed` — not the
`docker compose up` database on port 5433, which gets reseeded on every
backend container start. `conftest.py` refuses to run otherwise (see
`_refuse_to_run_against_a_seeded_database`) rather than producing results
that depend on which Postgres happened to be on the other end of the URL.
Use a second, dedicated database (`meridian_flow_test`) for the suite.

---

## Conventions — follow these, they are not suggestions

**Layering.** Routes call services. Services call repositories. Repositories
touch the database. Never put business logic in a route; never let a route
import a model directly for anything but a type hint.

**Errors.** Raise `AppError` subclasses from `app/core/exceptions.py`, never
`HTTPException`. One handler in `app/main.py` translates them to a consistent
JSON shape. Add a new subclass rather than reusing a vaguely-related one.

**Enums.** Every SQLAlchemy `Enum` column must pass
`values_callable=enum_values`. Omitting it persists the member *name* instead
of its value and every insert fails at runtime. See `app/models/enums.py`.

**Migrations.** Every schema change gets an Alembic migration. Never edit an
applied migration; add a new one.

**Types.** Full type hints. `mypy app` must pass with no new ignores.

**Comments.** This codebase documents *why*, not *what*. When you make a
non-obvious choice — a tradeoff, a workaround, a rejected alternative — write
it down at the point of the decision. Do not narrate what the code plainly
does.

**ADRs.** Any decision that would make a reviewer ask "why did you do it that
way?" gets a numbered ADR in `docs/decisions/`. Follow the existing format.

**Correlation IDs.** Every log line carries one automatically (see
`app/core/correlation.py`). Pass business context via `extra={...}` on log
calls — it lands as queryable top-level JSON keys.

---

## Security — hard rules

- Never commit secrets. `.env` is gitignored and must stay that way.
- Never read or echo `.env` or anything under `personal/`.
- Never log tokens, passwords, API keys, or raw provider credentials.
  Redact before persisting provider errors or payloads.
- RBAC is enforced **server-side**, always. A frontend check is a convenience,
  never a control.
- Webhooks are HMAC-verified. Do not add an unauthenticated inbound endpoint.
- Do not claim an integration was verified live unless it was actually run
  against the real provider and the result recorded. Simulated is fine —
  mislabelled is not.

---

## Git

- Work on `feature/enterprise-integration-reliability`. Do not commit to `main`.
- Never force-push, `git reset --hard`, `git clean`, or move an existing tag.
- Before committing, run `git status --short` and confirm no `.env`, no
  `personal/`, no caches, no `node_modules`.
- Commit messages: what changed and why, imperative mood, no "WIP".
- Run `ruff check .`, `mypy app`, and `pytest -q` before every commit. A red
  commit on this branch is worse than no commit.

---

## V2 scope

Nine modules, built in phases. See the project's phase plan.

1. Integration connection management (provider interfaces, health, correlation)
2. Salesforce (adapter + simulator)
3. n8n (self-hosted, version-controlled workflows)
4. Identity — Keycloak OIDC, then SAML PoC
5. SCIM 2.0 provisioning (documented subset)
6. Microsoft Graph + PowerShell scripts
7. Observability — OpenTelemetry, Prometheus, Loki, Tempo, Grafana
8. Support operations console
9. Failure Lab (development-only failure injection) + runbooks

**Provider pattern.** Every external provider is an interface with two
implementations: live and simulated, satisfying the same contract tests. The
simulator is a first-class citizen, not a stub — it must reproduce realistic
failures (expired token, rate limit, missing permission, duplicate delivery).

**Docker Compose profiles.** The base stack stays at V1's five services so
`docker compose up` still works for someone who just cloned the repo.
Identity, integrations, and observability are opt-in profiles.

**Auth is dual-mode** (`AUTH_MODE=local|oidc`). Local JWT keeps tests hermetic;
Keycloak OIDC drives the real flow. Both resolve to the same `get_current_user`
and the same authorization layer. See ADR-0015.
