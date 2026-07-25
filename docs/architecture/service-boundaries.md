# Service Boundaries

Each module in `backend/app/services/` owns one concern. Rule: a service may call other services and repositories; a route may only call services, never repositories directly; a repository may only touch the DB, never call a service.

## auth

*(Added in Phase 3 — not in the original Phase 1 service list.)* Owns: verifying credentials, issuing JWTs. `services/auth/service.py` deliberately returns the same error for "no such email" and "wrong password" (`InvalidCredentialsError`) so a caller can't enumerate valid emails through the login endpoint's response.
Does not: decide *authorization* (what a role can do) — that's `app/api/deps.py`'s `require_role`, which sits at the API layer since it's about gating routes, not a business decision a service makes.
Calls: `repositories/user_repo`.

## workflow

Owns: starting instances, executing steps in order, pausing/resuming, validating state transitions, marking complete/failed/cancelled.
Does not: know how to evaluate a business rule, call OpenAI, or call an MCP tool — it delegates to `rules`, `ai`, and `integrations` for those, and only orchestrates the sequence and state.
Calls: `rules`, `approvals`, `ai`, `integrations`, `notifications`, `audit`.

## approvals

Owns: creating `ApprovalRequest` rows, recording `ApprovalDecision`, sequencing multi-step approval chains, telling `workflow` when a step can unblock.
Does not: decide *who* needs to approve — that's a rules-engine output the workflow engine hands it.
Calls: `notifications`, `audit`.

## rules

Owns: pure, deterministic functions — approval routing, access-risk classification, whether AI should be invoked, whether escalation applies. Input in, decision out, no side effects, no DB writes.
Does not: touch the database or call external services. This is what makes it trivially unit-testable.
Calls: nothing. It's a leaf.

## ai

Owns: building prompts, calling OpenAI, validating the response against a Pydantic schema, computing/propagating confidence + `requires_human_review`, and — for the onboarding recommendation task specifically — acting as an MCP client to call the read-only `lookup_employee` tool for context before generating a recommendation.
Does not: approve anything, call Jira/Slack/Calendar, or decide workflow routing.
Calls: `integrations` (only for the `lookup_employee` MCP tool), `audit`.

## integrations

Owns: the MCP client wrapper — the single place that knows how to reach the MCP server. Wraps every tool call with retry/backoff, timeout, and an `MCPToolExecution` audit row.
Does not: contain business logic about *when* to call a tool — callers (workflow engine, ai service) decide that; this module just executes the call safely and logs it.
Calls: `audit`. Talks to the MCP server process over the network.

## notifications

Owns: writing `Notification` rows (in-app) and, when a Slack notification is warranted, delegating the actual send to `integrations` (which calls the Slack MCP tool).
Does not: call Slack directly — that would bypass the MCP audit trail.
Calls: `integrations`, `audit`.

## audit

Owns: writing `AuditLog` rows. Every other service calls this; nothing writes to `AuditLog` directly from a repository or route.
Does not: make decisions or branch workflow logic based on what it logs — it's write-only from the rest of the system's perspective.
Calls: nothing. Leaf, like `rules`.

## Repositories

One per aggregate (`employee_repo.py`, `workflow_repo.py`, `approval_repo.py`, `task_repo.py`, `notification_repo.py`, `audit_repo.py`, `ai_execution_repo.py`, `mcp_execution_repo.py`). Plain SQLAlchemy queries, no business logic, no calls to other services. This is what keeps services testable with a fake/mock repository instead of a real DB in unit tests.

## Why this split, not fewer/bigger service files

The spec explicitly warns against giant service classes and circular dependencies. Separating `rules` from `workflow` and keeping `rules` side-effect-free means the rules engine can be unit tested with zero DB/mocking setup — this is also the answer to "prove your business rules are separate from routing code" that shows up as a hiring requirement (Automation Engineer, Business Systems Engineer). Separating `ai` from `integrations` means the AI-failure-fallback path can be tested without needing a live or mocked MCP server, and the MCP retry/audit logic can be tested without needing a live or mocked OpenAI client.
