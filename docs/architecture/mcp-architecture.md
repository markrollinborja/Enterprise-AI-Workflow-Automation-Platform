# MCP Architecture

This is the centerpiece of Project #2 — the thing Project #1 (AI IT Ticket Automation Platform) doesn't have. It gets more depth here than its line count would suggest on purpose.

## What MCP is, in plain terms

The Model Context Protocol is a standard for exposing a fixed set of typed, permissioned "tools" (functions) to an AI agent, over a defined protocol, instead of the AI hitting raw REST APIs directly. A tool has a name, a typed input schema, a typed output schema, and runs on a server the AI talks to as a client. The server — not the AI — decides what's allowed, validates inputs, and can log every call. This is the difference between "an LLM that can theoretically call any API if you let it" and "an LLM that can call exactly four named, audited, least-privilege actions and nothing else."

## What problem it solves here

Two different callers in this system need to trigger the same external actions (create a Jira ticket, send a Slack message, schedule a calendar event, look up an employee):

1. The **workflow engine**, deterministically — "this workflow definition says step `create_it_tasks` calls `create_jira_task`, so call it now with these exact parameters."
2. The **AI service**, agentically — the LLM generating an access recommendation may decide it needs more context (e.g. who the employee's manager is) and calls `lookup_employee` itself, mid-reasoning, before producing its answer.

Without MCP, these would be two different code paths: the workflow engine calling a `JiraClient` class directly, and the AI service either not having tool access at all or getting bespoke function-calling wired up separately for OpenAI's API. MCP unifies both into one server, one set of typed tool definitions, one audit log, and one place to enforce least privilege — regardless of which caller invokes a tool.

## Real server, not a disguised module

`mcp_server/` runs as its own process (its own Docker Compose service), speaking MCP over HTTP/SSE transport. The backend and the AI service connect to it as MCP *clients* over the network — they do not import its code and call Python functions directly. This matters: a `services/mcp_tools.py` module that's organized like tools but called as plain function imports isn't actually demonstrating MCP, it's demonstrating good code organization. Running a real server with a real protocol boundary is what makes "I built and used an MCP server" a true claim in an interview, not a stretch.

## The four tools

| Tool | Type | Called by | Destructive? |
|---|---|---|---|
| `create_jira_task` | write | workflow engine (step type `mcp_tool`) | Yes — creates a real Jira issue |
| `send_slack_notification` | write | workflow engine + notifications service | Yes — sends a real message |
| `schedule_calendar_event` | write | workflow engine | Yes — creates a real calendar event |
| `lookup_employee` | read | AI service (agentic) | No |

Every write tool requires that the workflow has already passed any required approval gate before the step that calls it executes — the tool itself doesn't know about approvals, but the workflow engine will not schedule an `mcp_tool` step whose preceding `approval` step isn't `completed`. This is the concrete implementation of Principle 3 (human-in-the-loop): the AI can *read* (`lookup_employee`) freely, but every *write* tool sits behind a workflow position that's gated by human approval upstream.

Each tool has a typed Pydantic input and output schema, e.g.:

```python
class CreateJiraTaskInput(BaseModel):
    project_key: str
    summary: str
    description: str
    issue_type: Literal["Task", "Story"]
    assignee_email: EmailStr | None = None

class CreateJiraTaskOutput(BaseModel):
    issue_key: str
    issue_url: str
    status: Literal["created", "failed"]
```

## Which actions go through MCP, and which don't

MCP is the boundary specifically for **actions on external systems that an AI agent might plausibly need to invoke or that the workflow engine takes as a scripted action**: Jira, Slack, Calendar, employee lookup. It is *not* used for:

- Internal DB reads/writes (employee CRUD, workflow state transitions, writing a `WorkflowEvent`/`AIExecution`/`MCPToolExecution` row) — these are ordinary repository/service calls. There's no "external system" boundary to cross and no reason to add a network hop.
- Auth (login, token issuance) — internal, not a tool an agent invokes.
- The OpenAI call itself — the AI service calls OpenAI's API directly to get a completion; MCP is for the *tools the completion's tool-calling loop can invoke*, not the LLM call itself.

The rule of thumb documented for this project: if it's "the AI agent might want to call this to get information or take an action in the outside world," it's an MCP tool. If it's "the backend needs to read/write its own database," it's a plain service/repository call.

## How the AI agent discovers and invokes tools

For the onboarding access-recommendation task, the AI service passes the `lookup_employee` tool's schema to OpenAI as part of the request (OpenAI-native function/tool calling). If the model's response includes a tool call, the AI service resolves it against the MCP client (not by pattern-matching the model's output against arbitrary functions — only tools actually registered with the MCP server can be invoked), executes it, logs an `MCPToolExecution` row with `caller = ai_agent`, feeds the result back to the model, and continues until the model returns a final structured recommendation. The model never gets direct network access — every tool call round-trips through the MCP client, which is the enforcement point for input validation and logging.

For workflow-engine-invoked tools (`create_jira_task`, `send_slack_notification`, `schedule_calendar_event`), there's no discovery step — the workflow definition JSON names the tool and supplies the parameters directly. `caller = workflow_engine` on those `MCPToolExecution` rows.

## Permissions, least privilege, auditability

- Each tool validates its own input against its Pydantic schema server-side — a malformed or out-of-range call fails at the MCP server, not silently downstream.
- `lookup_employee` returns only fields relevant to an access decision (name, title, department, manager, start date) — not `personal_email`, salary, or anything not needed for the task calling it.
- Every tool call — success or failure, from either caller — writes one `MCPToolExecution` row (see [data-model.md](./data-model.md)): tool name, caller, input, output, status, duration, error if any.
- No tool performs an irreversible action without the workflow-level approval gate already having passed (see above).

## Error handling and mock mode

Every tool supports `MOCK_MODE` (env-var driven, **default true**). In mock mode, tools return realistic canned responses (a fake Jira issue key, a fake calendar event ID) instead of calling the real external API — this is what makes the demo scenarios reliably repeatable in an interview without depending on live Jira/Slack/Google credentials being valid at that moment. Real mode is fully implemented and documented in `docs/testing/` for anyone who wants to wire up real dev accounts, but the default, demo-ready path never depends on an external service being up.

On a real-mode failure (timeout, 5xx, auth error), the tool call fails, `integrations` retries with backoff up to a configured max, and if retries are exhausted the calling `WorkflowStepInstance` moves to `failed` and the instance moves to `waiting_external` → `failed` per the state model — never a silent swallow, never a workflow stuck in limbo with no record of what happened.
