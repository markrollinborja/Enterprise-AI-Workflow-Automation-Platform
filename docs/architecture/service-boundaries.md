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
- `executors.py` (Phase 6; `ai_action` made real in Phase 9) — `execute_ai_action` dispatches to `services/ai/service.py` for real; `execute_mcp_tool_stub` is still a stub standing in for the MCP client (Phase 10), reading the `force_failure_steps` test hook from the workflow's own `input_data` — the same hook that let the retry/backoff/pause path get built and tested before the real integration exists. Phase 10 replaces only what's inside that one remaining function.
- `service.py` (Phase 6) — the engine itself: `start_workflow`, `advance_workflow`, `resume_workflow_step`. Owns starting instances, executing steps in definition order, evaluating conditions to skip steps, dispatching by step type, applying each step's configured `failure_behavior` (retry/fail_workflow/continue), and pausing/resuming for human approval. Built entirely on `state_machine.py`'s transition functions — never writes `.status` directly.

Does not: call OpenAI or MCP directly (Phase 9's `services/ai` and Phase 10's MCP client own that, `executors.py` is the seam between them and `service.py`), or write `AuditLog` rows (Phase 13). It does, as of Phase 7, create `ApprovalRequest` rows the moment a step pauses (`_create_approval_request`) and resolve who they're assigned to (`_resolve_approver`) — see the note under `approvals` below for why that lives here instead of in the approvals service. As of Phase 9, `_apply_step_result` also carries a failed step's `output_data` forward when the executor provides one (previously only successful steps kept their output) — this is what lets a downstream condition safely read `recommend_access.requires_human_review` even when the AI call itself failed and fell back to a safe default, instead of raising `ConditionEvaluationError` over a step that never completed.
Calls: `repositories/workflow_definition_repo`, `workflow_instance_repo`, `workflow_step_repo`, `workflow_event_repo`, `approval_request_repo`, `employee_repo`, `user_repo`, and (via `executors.py::execute_ai_action`) `services/ai/service.py`.

**Worker.** `app/workers/runner.py` polls `list_ready_to_advance()` every few seconds and calls `advance_workflow` on each result — the same function `start_workflow`/`resume_workflow_step` call inline. One execution path, two callers (see ADR-0002 and [background-jobs.md](./background-jobs.md)).

## approvals

*(Built in Phase 7.)* Module: `app/services/approvals/service.py`.

Owns: the human-facing side of approvals — `list_pending_for_user` (what's in my inbox: assigned-to-me, my role's pool, or everything for Administrators) and `decide` (authorize the caller against the specific `ApprovalRequest`, record an `ApprovalDecision`, flip the request's status, then resume or end the underlying workflow instance).

Does not: create `ApprovalRequest` rows, or decide *who* an approval is assigned to — both happen in `services/workflows/service.py` when a step pauses, not here. This is a deliberate correction to the original Phase 1 sketch (which had `approvals` owning creation *and* the workflow engine calling into `approvals` to pause): that's circular. The actual dependency only runs one way — `approvals` calls `services/workflows/service.py::resume_workflow_step` to act on a decision; `workflows` never calls into `approvals`. Also does not send notifications or write audit rows yet (Phase 11, Phase 13).

Calls: `repositories/approval_request_repo`, `approval_decision_repo`, and `services/workflows/service.py` (one-way, see above).

## rules

*(Built in Phase 8.)* Module: `app/services/rules/service.py`.

Owns: `classify_request_risk` (an access request's overall risk is the higher of the application's risk and the requesting employee's risk — "highest wins") and `should_auto_approve` (only `LOW` overall risk skips human approval). Input in, decision out, no side effects, no DB writes — see `tests/test_rules.py`, which needs no fixtures at all.
Does not: decide *which* approval steps run for a given risk level — that routing already lives in `workflows/software_access_request.json`'s own step `condition` strings (`input.application_risk_level in [...]`), evaluated by `conditions.py`. `rules` only computes the risk and the auto-approve flag; the workflow JSON is the one place that turns a risk level into a specific approval chain. Also does not decide whether AI should be invoked or whether escalation applies — no V1 workflow needs either rule yet, so they're not built ahead of a real caller.
Calls: nothing. It's a leaf, same as `conditions.py` and `state_machine.py`.

## applications / access_requests

*(Built in Phase 8.)* `applications` (`app/services/applications/service.py`) is a thin read-only layer over the `Application` catalog — same shape as `employees`/`departments`, no write path in V1 (the catalog is seed-managed).

`access_requests` (`app/services/access_requests/service.py`) owns the second workflow's entry point: resolving the caller's linked `Employee`, looking up the requested `Application`, calling `rules.classify_request_risk`/`should_auto_approve`, and calling `services/workflows/service.py::start_workflow` with the result folded into `input_data`. This is the module that actually proves the workflow engine is reusable, not onboarding-shaped code with a second JSON file attached — it's a different service, composing the same engine, rules, and state machine `employees`/`approvals` also sit on top of.
Does not: decide risk (that's `rules`) or execute workflow steps (that's `workflows/service.py`). Does not accept `employee_id` as client input — it's always derived from the authenticated caller's own linked employee record, so one user can't submit a request as another.
Calls: `repositories/application_repo`, `employee_repo`, `services/rules/service.py`, `services/workflows/service.py::start_workflow`.

## ai

*(Built in Phase 9.)* Module: `app/services/ai/service.py`.

Owns: `execute_ai_task`, the dispatcher `services/workflows/executors.py::execute_ai_action` calls for every `ai_action` step. Builds prompts, calls OpenAI (`client.chat.completions.parse`, structured Pydantic output — never hand-parsed free text), computes/propagates `confidence_score` + `requires_human_review` (only when the step's `requires_review` flag enables it — see `schemas/workflow_definition.py`), and writes one `AIExecution` audit row per call, success or failure. `recommend_access_package`'s output is structurally constrained to the current `AccessPackage` catalog via a dynamically-built `Literal` enum — the model cannot name a package that doesn't exist (Principle 2). Any failure (missing API key, network error, a response that fails validation) degrades to a `StepExecutionResult` the engine's existing retry/fail/continue machinery already handles — no new failure-handling code needed at the engine level.
Does not: call MCP for its employee lookup, despite the original Phase 1 sketch of this section describing that — see ADR-0011 for why (Phase 10 hasn't built the real MCP server yet; standing one up early for one internal read isn't worth it). Calls `employee_repo` directly instead. Also does not approve anything, call Jira/Slack/Calendar, or decide workflow routing.
Calls: `repositories/employee_repo`, `access_package_repo`, `ai_execution_repo`.

## integrations

Owns: the MCP client wrapper — the single place that knows how to reach the MCP server. Wraps every tool call with retry/backoff, timeout, and writes the `MCPToolExecution` row itself, directly, on every call, success or failure.
Does not: contain business logic about *when* to call a tool — callers (workflow engine, ai service) decide that; this module just executes the call safely and logs it. There's no separate audit-writing service it hands that off to — see `## dashboard` below for why.
Calls: `repositories/mcp_tool_execution_repo`. Talks to the MCP server process over the network.

## notifications

*(Built in Phase 11.)* Module: `app/services/notifications/service.py`.

Owns: `notify()`, the single entry point `services/workflows/service.py` calls at the three points a workflow event matters to a specific person — `APPROVAL_REQUESTED` (a specifically-assigned approver only, in-app + Slack), `WORKFLOW_COMPLETED` (the submitter, in-app only), `WORKFLOW_REJECTED` (the submitter, in-app + simulated email). Always writes an in-app `Notification` row; Slack/email are opt-in per call, one row per (event, channel) rather than one row listing multiple channels. `recipient=None` (no linked `User`, e.g. an onboarding new hire with no login yet) is a silent no-op, not an error. A failed Slack send is caught and recorded as its own `FAILED` row — never raised, never blocks the in-app row (mirrors `notify_slack`'s own `failure_behavior=continue`). Email is simulated (formatted, logged, written as its own row) — no SMTP/Gmail integration in V1, matching the project's non-goals.
Does not: call Slack directly — real sends go through `integrations` (the Slack MCP tool), so every notification-triggered Slack call is audited in `MCPToolExecution` exactly like any other Slack call. Does not decide *whether* an event is notification-worthy — that judgment lives in the caller (`services/workflows/service.py`). No SLA timers, escalation, or resend — V1 is one-time notify only (explicit scope cut; those are V2 features).
Calls: `repositories/notification_repo`, `integrations` (for Slack).

## dashboard

*(Built in Phase 12.)* Module: `app/services/dashboard/service.py`. Read-only — the admin dashboard's entire backend surface (`GET /dashboard/summary`, `GET /workflow-instances` [+ `?status=`, + `/{id}`], `GET /audit-log`), all gated `require_role(ADMINISTRATOR)`.

Owns: `get_summary` (counts + breakdowns for the Overview page), `list_workflow_instances`/`get_workflow_instance_detail` (the Workflows, Failed Workflows, and Workflow Detail pages — one summary shape serves both the general list and the failed-only list via `?status=failed`, see `WorkflowInstanceSummaryResponse`'s docstring), and `build_audit_timeline` (the Audit Log page and Workflow Detail's per-instance timeline — same function, `workflow_instance_id` set or not).

Does not: write anything, ever — not a single `db.add()` in this module. This is the module that replaces what the original Phase 1 sketch called an `audit` service: rather than a dedicated write path every other service calls to log an `AuditLog` row, `build_audit_timeline` composes a read-time view over rows every other service was already writing for its own reasons (`WorkflowEvent`, `ApprovalRequest`/`ApprovalDecision`, `AIExecution`, `MCPToolExecution`, `Notification`). See `data-model.md`'s "Cuts from the original list" and this module's own docstring for the full reasoning, including the documented V1 scale limit on the global (cross-instance) case.

Calls: `repositories/workflow_instance_repo`, `workflow_event_repo`, `approval_request_repo`, `ai_execution_repo`, `mcp_tool_execution_repo`, `notification_repo`.

## Repositories

One per aggregate: `user_repo.py`, `department_repo.py`, `employee_repo.py`, `application_repo.py`, `access_package_repo.py`, `workflow_definition_repo.py`, `workflow_instance_repo.py`, `workflow_step_repo.py`, `workflow_event_repo.py`, `approval_request_repo.py`, `approval_decision_repo.py`, `ai_execution_repo.py`, `mcp_tool_execution_repo.py`, `notification_repo.py`. No `task_repo.py` or `audit_repo.py` — see `data-model.md`'s cuts for `Task`/`AuditLog`. Plain SQLAlchemy queries, no business logic, no calls to other services. This is what keeps services testable with a fake/mock repository instead of a real DB in unit tests.

## Why this split, not fewer/bigger service files

The spec explicitly warns against giant service classes and circular dependencies. Separating `rules` from `workflow` and keeping `rules` side-effect-free means the rules engine can be unit tested with zero DB/mocking setup — this is also the answer to "prove your business rules are separate from routing code" that shows up as a hiring requirement (Automation Engineer, Business Systems Engineer). Separating `ai` from `integrations` means the AI-failure-fallback path can be tested without needing a live or mocked MCP server, and the MCP retry/audit logic can be tested without needing a live or mocked OpenAI client.
