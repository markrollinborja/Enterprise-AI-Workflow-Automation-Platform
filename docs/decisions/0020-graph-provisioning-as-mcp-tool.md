# ADR-0020: Microsoft 365 Provisioning Is an MCP Tool, and PowerShell Is Generated, Never Executed

**Status:** Accepted — 2026-08-11

**Context:** Module 6 pairs two things the original scope names together — "Microsoft Graph + PowerShell scripts" — and neither had an obvious home yet. Two real design questions needed answers before writing any code.

First: does Microsoft Graph get its own provider-adapter (the Salesforce pattern — `IntegrationConnection`, live/simulated implementations satisfying one contract, health checks) or does it become another MCP tool (the Jira/Slack/Calendar pattern — a workflow step that calls out to `mcp_server`)? These are different shapes for different jobs. Salesforce is queried for CRM data the platform reads and reacts to (an onboarding-triggering lead, an opportunity's stage). Graph, here, is asked to do exactly one write — create an M365 account — as a step embedded in a workflow that already has three other steps of that exact shape.

Second: what does "PowerShell scripts" mean for a platform whose own non-goals explicitly rule out "arbitrary user-authored code execution," and whose Principle 3 requires human approval before high-impact automated actions? Actually running a PowerShell script against a Windows/AD environment is a different platform entirely — it needs an execution target this stack does not have, and it would hand an AI-adjacent workflow engine the ability to run arbitrary commands against enterprise identity infrastructure, which is precisely the blast radius Principle 3 exists to bound.

**Decision:**

*Provisioning is an MCP tool.* `provision_m365_account` joins `create_jira_task`, `send_slack_notification`, and `schedule_calendar_event` as a step in the onboarding workflow (`workflows/employee_onboarding.json`), calling `mcp_server` exactly the way those three already do. It reuses `Settings.mcp_mock_mode`, the same mock/live split, the same `MCPToolExecution` audit row, the same retry/backoff path through `executors.py`. No new `IntegrationConnection` row, no new provider registry entry, no new health-check surface — there is nothing about this integration that needs the connection-management machinery Module 1 built for CRM-style read access.

*PowerShell is generated, never run.* `execute_provision_m365_account` — in both mock and live mode, identically — returns a `powershell_script` field: the `New-MgUser` invocation an IT admin would run by hand to reproduce or verify the same account creation using the Microsoft Graph PowerShell SDK. The platform's job stops at generating and displaying that text as a workflow-output artifact (visible in the dashboard's step detail, same as any other `mcp_tool` step's `output_data`). Nothing in this codebase invokes `pwsh`, opens a shell, or executes anything an admin didn't type themselves.

The generated script never contains a real password — it prompts (`Read-Host ... -AsSecureString`) rather than embedding one, for the same reason V1's SCIM-provisioned users get a random, immediately-discarded password (see `docs/architecture/scim.md`): a credential-shaped string sitting in workflow output that gets displayed on a dashboard is a credential that leaked, whether or not it was ever real.

**Alternatives considered:**

*A Graph provider-adapter, parallel to Salesforce* — rejected. The provider-adapter pattern's entire value is a live/simulated pair satisfying one contract that other code queries generically. Nothing here queries Graph generically; exactly one workflow step calls exactly one Graph operation. Building the adapter machinery for a single write would be scaffolding with no second caller, which is the definition of premature abstraction this project's principles warn against.

*Actually executing the generated PowerShell* — rejected outright, for the reasons in Context: no execution target exists in this stack, and building one would mean granting the workflow engine the ability to run arbitrary commands against enterprise identity infrastructure with no additional approval gate beyond whatever already gated the workflow step. If a future version needs real execution, that is a new, explicit capability requiring its own approval story — not something this ADR back-doors in by choosing the wrong noun for "PowerShell scripts."

*Skipping the PowerShell output when running in live mode* (since a live call has "already done the real thing") — rejected. The value of the generated script isn't limited to a substitute for live provisioning; it's a portable, human-readable audit artifact showing exactly what was requested, independent of whether Graph's API happened to be reachable that day. Identical behavior in both modes also means a demo run and a real run produce the same shape of evidence, which is worth more than saving one field's worth of output in live mode.

**Consequences:**

Real-mode Graph access needs an app registration with `User.ReadWrite.All` application permission (admin-consented) in a tenant — documented in `docs/architecture/microsoft-graph.md`, not yet exercised against a real tenant in this project (mirrors Salesforce's live-mode status before a developer org existed).

The onboarding workflow definition moved from version 3 to 4 (`workflows/employee_onboarding.json`) with the new `provision_m365_account` step inserted after `it_review_access` and before `create_it_tasks` — provisioning the account before Jira tasks and orientation get scheduled, on the theory that any of those could reasonably reference the account existing.

`mcp_server` gains no new external dependency and no new container in `docker-compose.yml` — it is one more tool file and one more `@mcp.tool()` registration, following exactly the shape the codebase already uses three times.
