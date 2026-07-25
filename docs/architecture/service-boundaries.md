# Service Boundaries

Each module in `backend/app/services/` owns one concern. Rule: a service may call other services and repositories; a route may only call services, never repositories directly; a repository may only touch the DB, never call a service.

## auth

*(Added in Phase 3 — not in the original Phase 1 service list.)* Owns: verifying credentials, issuing JWTs. `services/auth/service.py` deliberately returns the same error for "no such email" and "wrong password" (`InvalidCredentialsError`) so a caller can't enumerate valid emails through the login endpoint's response.
Does not: decide *authorization* (what a role can do) — that's `app/api/deps.py`'s `require_role`, which sits at the API layer since it's about gating routes, not a business decision a service makes.
Calls: `repositories/user_repo`.

## employees / departments

*(Added in Phase 4 — not in the original Phase 1 service list, same reasoning as `auth` in Phase 3: the spec's service list covers the workflow engine and its supporting concerns, but the directory that the workflow engine operates *on* needs its own thin layer first.)*
Owns: CRUD-ish reads and writes on the org directory — listing/creating/updating employees and departments, validating department/manager references exist, enforcing `work_email` uniqueness, and mapping ORM rows to API responses (including the derived `department_name`/`manager_name` fields so the frontend never resolves a UUID itself).
Does not: know anything about workflows, approvals, or access packages. An `Employee` row can exist with zero workflow instances ever touching it — onboarding is a *process that references* an employee, not something the employee record depends on.
Calls: `repositories/department_repo`, `repositories/employee_repo`. No audit-log or notification calls yet — those get wired in once a workflow (Phase 5+) actually mutates an employee's state as a side effect; a plain HR-entered directory edit isn't itself a workflow event.

## workflows

Module: `app/services/workflows/` (plural — matches `employees`/`departments`, the resource-collection naming convention already used elsewhere in this codebase, rather than `auth`'s singular concept-service naming).

Two pieces exist as of Phase 5, both deliberately DB-free and side-effect-free beyond the object/row passed in — no orchestration logic lives here yet:

- `state_machine.py` — `transition_instance()` / `transition_step()`, the only functions allowed to write `WorkflowInstance.status` / `WorkflowStepInstance.status`. Implements the transition tables from [workflow-state-model.md](./workflow-state-model.md) exactly; unit-tested transition-by-transition in `tests/test_state_machine.py`.
- `definition_loader.py` — reads `workflows/*.json`, validates each against `WorkflowDefinitionSchema` (`app/schemas/workflow_definition.py`), and upserts into `WorkflowDefinition`. Called from `seed.py`, not from any request path.

Phase 6 adds `service.py` to this same module: starting instances, executing steps in order, pausing/resuming, marking complete/failed/cancelled — built on top of `state_machine.py` rather than duplicating transition logic inline.
Does not (Phase 6 scope): know how to evaluate a business rule, call OpenAI, or call an MCP tool — it will delegate to `rules`, `ai`, and `integrations` for those, and only orchestrate the sequence and state.
Calls (Phase 6 scope): `rules`, `approvals`, `ai`, `integrations`, `notifications`, `audit`.

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
