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

- `state_machine.py` (Phase 5) — `transition_instance()` / `transition_step()`, the only functions allowed to write `WorkflowInstance.status` / `WorkflowStepInstance.status`. Unit-tested transition-by-transition in `tests/test_state_machine.py`.
- `definition_loader.py` (Phase 5) — reads `workflows/*.json`, validates each against `WorkflowDefinitionSchema`, and upserts into `WorkflowDefinition`. Called from `seed.py`, not from any request path.
- `conditions.py` (Phase 6) — evaluates a step's `condition` string against workflow/step context using a whitelisted `ast`-based parser (no `eval()`/`exec()` — see the module docstring and `tests/test_conditions.py`'s explicit "malicious expression" tests). A leaf module: no DB access, no calls out.
- `executors.py` (Phase 6) — stub implementations of `ai_action`/`mcp_tool` step execution, standing in for the AI service (Phase 9) and MCP client (Phase 10). Both stubs read test hooks (`force_failure_steps`, `ai_requires_review`) from the workflow's own `input_data`, which is what let the retry/backoff/pause path get built and tested before either real integration exists. Phase 9/10 replace only what's inside these two functions.
- `service.py` (Phase 6) — the engine itself: `start_workflow`, `advance_workflow`, `resume_workflow_step`. Owns starting instances, executing steps in definition order, evaluating conditions to skip steps, dispatching by step type, applying each step's configured `failure_behavior` (retry/fail_workflow/continue), and pausing/resuming for human approval. Built entirely on `state_machine.py`'s transition functions — never writes `.status` directly.

Does not: decide *who* needs to approve (that's a Phase 7 rules-engine/`ApprovalRequest` concern the engine will delegate to once it exists — Phase 6's `resume_workflow_step` is deliberately generic, taking a bare `decision`, and gets called directly in tests standing in for Phase 7's real approval routes), call a real OpenAI/MCP endpoint (Phase 9/10 own the *content* of `execute_ai_action_stub`/`execute_mcp_tool_stub`, not `service.py`), or write audit rows (Phase 13).
Calls: `repositories/workflow_definition_repo`, `workflow_instance_repo`, `workflow_step_repo`, `workflow_event_repo`.

**Worker.** `app/workers/runner.py` polls `list_ready_to_advance()` every few seconds and calls `advance_workflow` on each result — the same function `start_workflow`/`resume_workflow_step` call inline. One execution path, two callers (see ADR-0002 and [background-jobs.md](./background-jobs.md)).

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
