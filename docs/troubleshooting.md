# Troubleshooting

Real errors hit during this project's own development, not a hypothetical
FAQ. Commands are PowerShell (this project's documented shell).

## `docker compose exec backend ...` fails with "service \"backend\" is not running"

**Cause:** `docker compose up -d db` only starts the `db` service by name —
it does not start `backend`, `frontend`, `mcp_server`, or `worker`. Running
a command against a service that was never started fails this way.

**Fix:** start the full stack (no service name = all five declared
services):

```powershell
docker compose up -d
docker compose ps    # confirm all 5 services show "running"
```

Use `docker compose up -d db` only when you specifically want just Postgres
(e.g. running the backend outside Docker against a containerized DB).

## `pytest: error: unrecognized arguments: --cov=app --cov-report=term-missing`

**Cause:** `requirements-dev.txt` was updated to add `pytest-cov`, but an
existing local virtualenv was created before that change and never
reinstalled — the package genuinely isn't there yet.

**Fix:**

```powershell
cd backend        # or mcp_server
pip install -r requirements-dev.txt
pytest -v --cov=app --cov-report=term-missing
```

General rule: any time `requirements-dev.txt` or `requirements.txt` changes
(pulled from git or edited locally), rerun `pip install -r ...` before the
next test run — a stale venv fails with import or argument errors that look
unrelated to the actual dependency change.

## `git add`/`git commit`/`git status` fail with `fatal: Unable to create '...index.lock': File exists`

**Cause:** a leftover `.git/index.lock` file from a previous git process
that didn't exit cleanly (interrupted command, or in some cases OneDrive
sync colliding with an in-progress git operation, since this repo lives in
a OneDrive-synced folder). It is not a sign of a corrupted repo and not a
data-loss risk to remove — git creates this lock file at the start of any
write operation and deletes it when the operation finishes; a leftover one
just means the last one never got to the cleanup step.

**Fix:**

```powershell
cd path\to\Enterprise-Employee-Workflow-Automation-MCP
Remove-Item .git\index.lock
git status   # confirm it's gone and the repo is otherwise healthy
```

If it recurs frequently, it's worth checking Task Manager for a stuck `git`
process before deleting the lock file, though in practice this project
never found one — deleting was always sufficient.

## `git commit -m ""` (or a whitespace-only message) is rejected

**Cause:** git requires a non-empty commit message; a message that's only
whitespace is treated the same as empty.

**Fix:** always pass `-m` with real content:

```powershell
git commit -m "Phase 15: add API guide, security notes, troubleshooting guide"
```

## `alembic upgrade head` fails with `psycopg.errors.DuplicateObject: type "user_role" already exists`

**Cause:** a Postgres `ENUM` type created by an earlier migration run is
still present in the database, but Alembic's migration history doesn't
think that migration has run yet (a partially-applied migration, or a
database that was reset without also resetting Alembic's version table).

**Fix — for a local demo database, the fastest reliable fix is a clean
slate:**

```powershell
docker compose down -v          # -v removes the named volume (the DB's data)
docker compose up -d db
cd backend
alembic upgrade head
```

`-v` deletes all local demo data — safe for this project (seed data is
regenerated on next backend startup), but never run it against anything you
care about keeping.

## Postgres port `5432` already in use / `db` service fails to start

**Cause:** another Postgres instance (a different project's Docker
container, or a natively installed Postgres) is already bound to port
5432 on the host.

**Fix:** either stop the other instance, or remap this project's port in
`docker-compose.yml`'s `db` service (`"5433:5432"` instead of
`"5432:5432"`) and update `DATABASE_URL` in your `.env` to match
(`localhost:5433` when running the backend outside Docker; the in-network
`db:5432` hostname is unaffected since container-to-container traffic
doesn't go through the host port mapping at all).

## Backend starts but `/health/ready` returns an error / can't reach the database

**Cause:** almost always one of: `db` isn't up yet (Postgres takes a few
seconds to become ready after `docker compose up`), `DATABASE_URL` in
`.env` doesn't match `docker-compose.yml`'s `db` service credentials, or
migrations were never applied.

**Fix, in order:**

```powershell
docker compose ps                          # is db "running (healthy)"?
docker compose logs db --tail 50           # any startup errors?
cd backend
alembic upgrade head                       # migrations applied?
```

## Frontend can't reach the backend / requests fail with a CORS or network error

**Cause:** usually the backend isn't running, or the frontend's API base
URL doesn't match where the backend is actually listening.

**Fix:** confirm `docker compose ps` shows `backend` as running and
`http://localhost:8000/health` returns `{"status": "ok"}` in a browser
first — that isolates whether the problem is the backend or the frontend's
configuration.

## AI recommendations always come back as a graceful-fallback / low-confidence result

**Cause:** this is expected, not a bug, when `OPENAI_API_KEY` is unset in
`.env` — the AI service is designed to fail gracefully rather than crash the
workflow (see `docs/architecture/` AI service notes). Workflows still
complete end-to-end without a real key.

**Fix (only if you want real recommendations):** set a real
`OPENAI_API_KEY` in `.env` and restart the backend. Not required to run or
demo the rest of the platform.

## MCP tool calls always show `mock_mode: true` in the audit log

**Cause:** `MCP_MOCK_MODE=true` is the default and is what makes the demo
runnable with zero external credentials (no real Jira/Slack/Calendar
accounts needed).

**Fix (only if you want real integration calls):** set
`MCP_MOCK_MODE=false` and configure the real Jira/Slack/Calendar
credentials in `.env`, then restart both `backend` and `mcp_server`.
