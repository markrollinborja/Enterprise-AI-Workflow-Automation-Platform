# Integration Strategy

## The three external systems

**Jira Cloud** — free developer instance. `create_jira_task` tool posts to the Jira REST API (issue creation) using an API token + email for basic auth.

**Slack** — free developer workspace. `send_slack_notification` tool posts via the Slack Web API (`chat.postMessage`) using a bot token scoped to `chat:write` only — no broader scopes requested, per least-privilege.

**Google Calendar** — Calendar API v3. `schedule_calendar_event` tool creates an event on a specific shared calendar. Auth approach: a Google service account with access to one shared "Meridian Flow Demo" calendar, rather than per-user OAuth — per-user OAuth (consent screen, token refresh, per-employee authorization) is real-product complexity this project doesn't need to prove; a service account posting to one demo calendar demonstrates the same integration pattern (typed request in, typed result out, retried on failure) for a fraction of the setup cost.

## Mock mode is the default, not an afterthought

All three tools default to `MOCK_MODE=true` (env-configurable per tool). This is a deliberate reliability decision, not a shortcut: a demo or an interview screen-share should never depend on Jira/Slack/Google being reachable, credentials still being valid, or free-tier rate limits not having been hit that day. Mock responses are realistic (fake but well-formed issue keys, event IDs, message timestamps) so the rest of the system — audit rows, `MCPToolExecution` records, UI — behaves identically whether mock or real. Real mode is fully built and documented (`docs/testing/`) to prove it's not vaporware, just not the default demo path.

## Retry policy

Applied uniformly by the `integrations` service, not per-tool: exponential backoff (e.g. 2s, 8s, 30s), max 3 attempts, only for transient failures (timeouts, 5xx, connection errors). Validation errors (malformed input caught by the tool's Pydantic schema) are never retried — retrying a request that will fail identically every time just delays the failure. This distinction (retry transient, fail-fast on permanent) is called out explicitly because it's an easy thing to get wrong and a good thing to be able to explain in an interview.

## Failure path (what the demo actually shows)

Calendar tool fails (simulated, even in mock mode there's a `force_failure` test hook for the demo) → step `failed`, error logged → retry scheduled per backoff → retry succeeds → workflow resumes from `waiting_external` back to `running` → audit log shows both attempts, distinguishable by `attempt_number` on the `MCPToolExecution` rows. This is Demo Scenario 3 from Phase 0.
