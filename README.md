# Meridian Flow

Enterprise Employee Workflow Automation Platform — a reusable workflow orchestration system that automates internal employee processes (onboarding, software access requests) through configurable workflows, human approval chains, business rules, AI-assisted recommendations, and MCP-powered integrations, with complete auditability.

**Status:** Version 1 in active development. This README documents what's built so far (Phase 2 of the build) — not a finished product. See [docs/decisions/](docs/decisions/) for the reasoning behind every major architecture choice, and [docs/architecture/](docs/architecture/) for how the system fits together.

## What's here right now

- FastAPI backend skeleton with structured config, logging, and `/health` + `/health/ready` endpoints
- React + TypeScript + Vite + Tailwind CSS frontend skeleton that confirms it can reach the backend
- Postgres via Docker Compose
- Alembic migration scaffolding (no models yet — those land in Phase 4)
- Linting (Ruff + MyPy for backend, ESLint for frontend) and a basic pytest suite
- GitHub Actions CI running lint + tests on every push

Workflow engine, approvals, business rules, AI service, and MCP server are not built yet — those are Phases 4-10. This is intentionally a thin, runnable base to build on.

## Running locally (Docker Compose — recommended)

```bash
cp .env.example .env
# edit .env if you want, defaults work for local dev
docker compose up --build
```

- Backend: http://localhost:8000 (docs at http://localhost:8000/docs)
- Frontend: http://localhost:5173
- Postgres: localhost:5432 (user/pass/db: `meridian`/`meridian`/`meridian_flow`)

The frontend's landing page shows a live connection status to the backend — green means the whole stack is wired up correctly.

## Running the backend without Docker

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
# requires a local Postgres reachable at the DATABASE_URL in .env, or edit it to point elsewhere
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
# backend
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
workflows/       Versioned JSON workflow definitions (Phase 5)
docs/
  architecture/  System design docs — read these first
  decisions/     ADRs — the "why" behind every major choice
docker-compose.yml
.env.example
```

## Companion project

This is the second of two portfolio projects demonstrating enterprise automation engineering. The first, [AI IT Ticket Automation Platform](#), automates a single IT ticket workflow end-to-end (Jira, Slack, rule engine, AI fallback). This project proves the *reusability* of a workflow engine across multiple business processes (onboarding, access requests) and adds MCP-based AI agent tool-calling, which the first project doesn't have.
