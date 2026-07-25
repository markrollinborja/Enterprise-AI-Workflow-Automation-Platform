# Meridian Flow

Enterprise Employee Workflow Automation Platform — a reusable workflow orchestration system that automates internal employee processes (onboarding, software access requests) through configurable workflows, human approval chains, business rules, AI-assisted recommendations, and MCP-powered integrations, with complete auditability.

**Status:** Version 1 in active development. This README documents what's built so far (Phase 6 of the build) — not a finished product. See [docs/decisions/](docs/decisions/) for the reasoning behind every major architecture choice, and [docs/architecture/](docs/architecture/) for how the system fits together.

## What's here right now

- FastAPI backend skeleton with structured config, logging, and `/health` + `/health/ready` endpoints
- Local JWT auth: login, `/auth/me`, six roles (employee, manager, hr, it, security, administrator), server-side role enforcement (`/users` is administrator-only)
- Employee directory: `Employee` + `Department` models (self-referential manager relationship), `/employees` and `/departments` APIs (read for any authenticated user, write restricted to HR/Administrator), a React table view in the dashboard
- Workflow definitions and state model: `WorkflowDefinition` / `WorkflowInstance` / `WorkflowStepInstance` / `WorkflowEvent` models, a validated JSON schema for workflow definitions, the two V1 workflow templates (`workflows/employee_onboarding.json`, `workflows/software_access_request.json`), and an enforced state machine for both instance and step transitions
- **Workflow execution engine** (Phase 6): `start_workflow` / `advance_workflow` / `resume_workflow_step` actually run a workflow — executing steps in definition order, evaluating `condition` strings with a safe (non-`eval`) expression parser, dispatching to stub `ai_action`/`mcp_tool` executors that stand in for the not-yet-built AI service and MCP server, applying each step's configured retry/fail/continue behavior, and pausing for human approval. A real polling worker (`app/workers/runner.py`, its own Compose service) picks up retry-scheduled steps once their backoff elapses. `docker compose up` now auto-starts one real onboarding instance for the demo new hire, paused at the manager-approval step — visible in the DB today, even before there's an approval inbox UI to resolve it
- React + TypeScript + Vite + Tailwind CSS frontend with a working login flow and employee directory table
- Postgres via Docker Compose, with Alembic migrations (`users`, then `departments` + `employees`, then `workflow_definitions` / `workflow_instances` / `workflow_step_instances`, then `workflow_events`)
- Nine demo employees / six demo user logins auto-seeded on `docker compose up`, at a fictional company (Cordant Industries) — see `backend/app/db/seed.py`
- Linting (Ruff + MyPy for backend, ESLint for frontend) and a pytest suite covering auth, the employee directory, the workflow state machine, the workflow definition loader/schema, the condition evaluator (including explicit "malicious expression" safety tests), and the execution engine (happy path, rejection, retry-and-recover, retries-exhausted, idempotency, worker polling)
- GitHub Actions CI running migrations + lint + tests on every push

Approvals (a real inbox/routing UI), business rules, the AI service, and the MCP server are not built yet — those are Phases 7-10. This is intentionally a thin, runnable base to build on.

## Demo users

All seeded with the password from `DEMO_PASSWORD` in `backend/app/db/seed.py` (`MeridianDemo123!` by default — a local-dev-only credential, change it in your own `.env`-driven seed if you ever expose this anywhere real).

| Email | Role |
|---|---|
| priya.anand@cordant.io | HR |
| daniel.osei@cordant.io | Manager |
| sam.whitfield@cordant.io | IT |
| renee.castillo@cordant.io | Security |
| jordan.lee@cordant.io | Employee |
| ava.thompson@cordant.io | Administrator |

## Running locally (Docker Compose — recommended)

```bash
cp .env.example .env
# edit .env if you want, defaults work for local dev
docker compose up --build
```

- Backend: http://localhost:8000 (docs at http://localhost:8000/docs)
- Frontend: http://localhost:5173
- Postgres: localhost:5432 (user/pass/db: `meridian`/`meridian`/`meridian_flow`)

The backend container runs migrations and seeds demo users automatically on startup (`alembic upgrade head && python -m app.db.seed`) before starting the API — that's why login works immediately after `docker compose up`, no manual setup step needed.

## Running the backend without Docker

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
# requires a local Postgres reachable at the DATABASE_URL in .env, or edit it to point elsewhere
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload
```

## Running the frontend without Docker

```powershell
cd frontend
npm install
npm run dev
```

## Testing and linting

```powershell
# backend — requires migrations applied against a reachable Postgres (see above)
cd backend
pytest
ruff check .
mypy app

# frontend
cd frontend
npm run lint
npm run build
```

## Project structure

```
backend/        FastAPI app (routes, services, repositories, models — see docs/architecture/service-boundaries.md)
mcp_server/      MCP server exposing Jira/Slack/Calendar/employee-lookup tools (Phase 10)
frontend/        React + TypeScript + Vite + Tailwind dashboard
workflows/       Versioned JSON workflow definitions (employee_onboarding, software_access_request)
docs/
  architecture/  System design docs — read these first
  decisions/     ADRs — the "why" behind every major choice
docker-compose.yml
.env.example
```

## Companion project

This is the second of two portfolio projects demonstrating enterprise automation engineering. The first, [AI IT Ticket Automation Platform](#), automates a single IT ticket workflow end-to-end (Jira, Slack, rule engine, AI fallback). This project proves the *reusability* of a workflow engine across multiple business processes (onboarding, access requests) and adds MCP-based AI agent tool-calling, which the first project doesn't have.
