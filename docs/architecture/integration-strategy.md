# Integration Strategy

## The three external systems

**Jira Cloud** — free developer instance. `create_jira_task` tool posts to the Jira REST API (issue creation) using an API token + email for basic auth.

**Slack** — free developer workspace. `send_slack_notification` tool posts via the Slack Web API (`chat.postMessage`) using a bot token scoped to `chat:write` only — no broader scopes requested, per least-privilege.

**Google Calendar** — Calendar API v3. `schedule_calendar_event` tool creates an event on a specific shared calendar. Auth approach: a Google service account with access to one shared "Meridian Flow Demo" calendar, rather than per-user OAuth — per-user OAuth (consent screen, token refresh, per-employee authorization) is real-product complexity this project doesn't need to prove; a service account posting to one demo calendar demonstrates the same integration pattern (typed request in, typed result out, retried on failure) for a fraction of the setup cost.

## Mock mode is the default, not an afterthought

All three tools default to `MOCK_MODE=true` (env-configurable per tool). This is a deliberate reliability decision, not a shortcut: a demo or an interview screen-share should never depend on Jira/Slack/Google being reachable, credentials still being valid, or free-tier rate limits not having been hit that day. Mock responses are realistic (fake but well-formed issue keys, event IDs, message timestamps) so the rest of the system — audit rows, `MCPToolExecution` records, UI — behaves identically whether mock or real. Real mode is fully built and documented (`docs/testing/`) to prove it's not vaporware, just not the default demo path.

## Retry policy

**Revised in Phase 10 (see ADR-0012) — this section originally described retry as living inside `services/integrations`, written before the workflow engine existed to provide a real mechanism.** In reality, `services/integrations/mcp_client.py::call_tool` calls a tool exactly once and reports success or failure; it does not retry internally. The actual retry is the workflow engine's own step-level mechanism, built in Phase 6 before this integration existed: exponential backoff (2s, 8s, 30s — `_BACKOFF_SCHEDULE_SECONDS` in `services/workflows/service.py`), up to a step's configured `max_attempts`, applied uniformly to every step type via `failure_behavior: retry` in the workflow JSON — not a Jira/Slack/Calendar-specific mechanism. Validation errors (a workflow step whose context can't build a valid tool call — see `MCPArgumentError` in `executors.py`) still aren't retried, since `failure_behavior` is set per step in the JSON, not inferred from the error type; a step author who wants fail-fast-on-bad-input behavior sets `failure_behavior: fail_workflow` for that step. This distinction (retry transient, fail-fast on permanent) is still the right one to be able to explain in an interview — it's just enforced one layer up from where this doc originally placed it.

## Failure path (what the demo actually shows)

Calendar tool fails (simulated, even in mock mode there's a `force_failure` test hook for the demo) → step `failed`, error logged → retry scheduled per backoff → retry succeeds → workflow resumes from `waiting_external` back to `running` → audit log shows both attempts, distinguishable by `attempt_number` on the `MCPToolExecution` rows. This is Demo Scenario 3 from Phase 0.
