# Security Notes

This consolidates the project's security posture into one place. It doesn't
repeat detail that already lives elsewhere and stays current on its own —
[`authentication.md`](../architecture/authentication.md) owns the JWT/RBAC
mechanics, [`data-model.md`](../architecture/data-model.md) owns exactly which
fields get redacted from audit rows. This doc answers the five questions the
project spec asks for directly: what's stored and why, who can access it,
how secrets are handled, what's deliberately not logged, and what a real
production deployment would still need.

## What data is stored, and why

| Data | Where | Why it's stored |
|---|---|---|
| Employee PII (name, work email, optional personal email, job title, department, manager, employment type, start date, status, location, risk level) | `employees` table | The system's core domain object — onboarding and access-request workflows exist to act on this data. |
| User credentials (email, bcrypt hash, role, optional linked `employee_id`) | `users` table | Authentication and RBAC. No plaintext password ever stored — see Secrets, below. |
| Access-request justifications (free text) | `access_requests` / workflow input data | The human-readable reason an approver needs to make a decision. |
| Approval decisions and notes | `approval_decisions` | The audit record of who approved/rejected what, and why. |
| AI execution records (task type, confidence, a short hand-built input summary, structured output) | `ai_executions` | Explainability — so an AI recommendation can be reviewed and audited after the fact, not just trusted. |
| MCP tool call records (tool name, params, result, mock/real mode) | `mcp_tool_executions` | Integration audit trail — proves what Jira/Slack/Calendar actions the system actually took. |
| Notifications | `notifications` | In-app inbox + delivery record per channel. |

None of this is real employee data — see [Demo Data](../../README.md#demo-users);
every row in a running instance is fictional, generated for demo purposes.

## Who can access what

Enforced server-side in the FastAPI dependency layer
(`app.api.deps.require_role`), independent of what the frontend shows or
hides — a request with the wrong role's token is rejected with `403`
regardless of the UI. Full endpoint-by-endpoint detail is in the
[API guide](../api/api-guide.md); the summary by role:

| Role | Can do |
|---|---|
| Employee | View employee directory and application catalog, submit access requests for themselves, view/act on their own approval inbox and notifications |
| Manager | Everything Employee can, plus: decide approvals assigned to them (typically onboarding/access-request manager approval) |
| HR | Everything Employee can, plus: create/update employees, create departments |
| IT | Everything Employee can, plus: decide IT-level approvals |
| Security | Everything Employee can, plus: decide Security-level approvals (high-risk access requests) |
| Administrator | Everything above, plus: full user list, dashboard summary, all workflow instances, global audit log, manual retry of failed workflow steps |

`GET /employees` and `GET /applications` are readable by any authenticated
user (like most internal org directories) — access control is on the
*write* paths (create/update employee, decide an approval, retry a step),
not on reading the roster.

## Secrets management

- All secrets are environment variables, never hardcoded. `.env` is
  gitignored; `.env.example` ships with placeholder values only
  (`JWT_SECRET_KEY=change-me-generate-a-real-secret`, blank API tokens).
- `JWT_SECRET_KEY` is meant to be generated locally
  (`python -c "import secrets; print(secrets.token_hex(32))"`), never
  reused from the example file.
- CI (`.github/workflows/ci.yml`) uses a dummy `JWT_SECRET_KEY: ci-test-secret`
  scoped only to the ephemeral, throwaway Postgres service each workflow run
  spins up and tears down — not a real secret, not reused anywhere else.
- External integration credentials (Jira, Slack, Google Calendar, OpenAI)
  are all optional while `MCP_MOCK_MODE=true` (the default) — the demo runs
  end-to-end with zero real credentials configured.
- The Jira fulfillment webhook (`POST /webhooks/jira`) is authenticated by
  HMAC-SHA256 signature verification (`JIRA_WEBHOOK_SECRET`), not a JWT —
  Jira can't hold a user session, so the shared-secret signature is the
  actual authentication for that one inbound endpoint. Blank in local dev,
  which makes the route refuse every request with `401` rather than
  silently accept unsigned ones.
- Passwords are hashed with bcrypt (`passlib`) before storage — never
  logged, never returned in any API response, never appear in audit rows
  (see redaction rules below).

## What's never logged or persisted in audit metadata

Full detail and reasoning: [`data-model.md` § "What's NOT logged in
metadata / what gets redacted"](../architecture/data-model.md). Summary: raw
passwords/hashes, personal email, raw JWTs, and any third-party API
key/token are excluded by construction from `AIExecution` and
`MCPToolExecution` rows at the point each row is written — not filtered
later at read time. `AIExecution.input_summary` is a deliberately short,
hand-built description (e.g. job title + department) rather than a full
prompt dump, so a sensitive free-text field like an access-request
justification doesn't end up persisted in full by accident. The Audit Log
page adds a second layer on top: its per-entry metadata is built from a
small, named field allowlist, never a wholesale dump of a source row.

## Database-level safeguards

Foreign keys with `ON DELETE` behavior appropriate to each relationship
(e.g. an `Employee` can't be deleted while a `WorkflowInstance` still
references it), `NOT NULL` constraints on required fields, and Postgres
enum types for every status/role column (so `'aproved'` is a database
error, not a silent bad row). Alembic migrations are the only way schema
changes reach the database — no manual `ALTER TABLE` against a running
instance.

## What would need to change for a real production environment

This is a portfolio project, not a production system — these gaps are
named deliberately, not hidden:

- **Token lifecycle.** 8-hour access tokens with no refresh flow and no
  revocation list. Production needs short-lived access tokens, a refresh
  flow, and a way to invalidate a token before it expires (e.g. on
  password change or account deactivation).
- **Secrets storage.** Flat `.env` files are fine for local dev; production
  needs a real secrets manager (AWS Secrets Manager, HashiCorp Vault, or
  equivalent) with rotation, not environment variables baked into a
  container image or `.env` file on a host.
- **Transport security.** No TLS termination is configured anywhere in this
  project (local Docker Compose is plain HTTP) — production needs TLS at
  the load balancer or ingress, HSTS, and secure cookie/header defaults if
  cookies are ever introduced.
- **Rate limiting.** `POST /auth/login` has no throttling — production
  needs brute-force protection (rate limiting, account lockout, or both).
- **Audit log immutability.** The audit trail is synthesized at read time
  from operational tables an application-layer bug (or a sufficiently
  privileged direct DB access) could still alter. Production compliance
  requirements often call for an append-only or write-once audit store.
- **Encryption at rest.** Not configured for the local Postgres container.
  Production should enable disk-level encryption at minimum, and consider
  column-level encryption for the most sensitive PII fields.
- **Dependency and vulnerability scanning.** CI runs `ruff`/`mypy`/tests but
  no `pip-audit`/`npm audit`/Dependabot-equivalent gate yet.
- **Data subject rights.** No delete/export-my-data flow exists. A real HR
  system handling actual employee PII would need one for regulatory
  compliance (GDPR/CCPA-style requests), even for internal-only data.
- **Centralized logging and alerting.** Structured logs exist per-process;
  there's no shipping to a log aggregator, no alerting on repeated auth
  failures or elevated error rates.
