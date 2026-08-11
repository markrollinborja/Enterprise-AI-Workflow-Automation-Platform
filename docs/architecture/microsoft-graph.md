# Microsoft Graph Provisioning

`provision_m365_account` — an MCP tool, not a provider-adapter. See
ADR-0020 for why: this is one workflow step doing one write, not a
generically-queried integration, so it reuses the Jira/Slack/Calendar
pattern rather than the Salesforce one.

---

## What it does

A step in `employee_onboarding.json` (`provision_m365_account`, inserted
after `it_review_access`, before `create_it_tasks`) that creates — or, in
mock mode, simulates creating — a Microsoft 365 account for the new hire,
and always returns the equivalent PowerShell an IT admin could run by hand.

| Field | Source |
|---|---|
| `display_name` | `f"{first_name} {last_name}"` |
| `user_principal_name` | `Employee.work_email` (doubles as the M365 UPN — this platform has no second email to draw one from) |
| `job_title` | `Employee.job_title` |
| `department` | `Employee.department.name` |

Output: `m365_user_id` (the Entra object ID), `user_principal_name`,
`status`, and `powershell_script` — the generated `New-MgUser` invocation.
The script is present and identical in shape whether the account was
really created or simulated; see ADR-0020.

---

## Mock vs. live

Same `MCP_MOCK_MODE` flag every other tool here uses (ADR-0005/ADR-0012) —
no separate toggle for Graph specifically.

**Mock** (default): returns a real-looking GUID, never calls the network.

**Live**: `POST /users` against Microsoft Graph, authenticated with an
app-only (client-credentials) token. Requires:

```
GRAPH_TENANT_ID=<your-tenant-id>
GRAPH_CLIENT_ID=<app-registration-client-id>
GRAPH_CLIENT_SECRET=<app-registration-client-secret>
```

### Setting up a free tenant and app registration

1. Sign up for the [Microsoft 365 Developer Program](https://developer.microsoft.com/microsoft-365/dev-program) — free, gives a sandbox E5 tenant with test users.
2. In the Entra admin center for that tenant: **App registrations → New registration**. No redirect URI needed — this is app-only, not a user sign-in flow.
3. **API permissions → Add a permission → Microsoft Graph → Application permissions → `User.ReadWrite.All`**, then **Grant admin consent**. Application permissions, not delegated — there is no signed-in user in this flow, matching why the client-credentials grant is the only one that makes sense here (same reasoning as Salesforce's OAuth client-credentials setup).
4. **Certificates & secrets → New client secret** — copy the value immediately, it is not shown again.
5. Set the three `GRAPH_*` variables above from the app registration's Overview page (Application (tenant) ID, Application (client) ID) and the secret from step 4.

---

## Why app-only, not delegated

A workflow engine provisioning accounts as part of an automated onboarding
run has no human sitting at a sign-in prompt — the delegated (user
sign-in) OAuth flow doesn't fit an unattended backend process, the same
reason Salesforce uses client-credentials rather than the authorization-code
flow the frontend uses for Keycloak. `.default` scope requests whatever
permissions the app registration was actually granted (step 3 above) rather
than asking per-call, which is Microsoft's convention for app-only Graph
access.

---

## What is verified

| Component | Status |
|---|---|
| Mock-mode account creation, PowerShell generation, field mapping | **Tested** (`mcp_server/tests/test_graph_tool.py`) |
| Wired into the onboarding workflow, argument-building from the employee record | **Tested** (`backend/tests/test_workflow_definitions.py`, `test_dashboard.py`) |
| Live mode against a real Microsoft 365 Developer tenant | **Not verified** — no tenant has been set up for this project yet, mirroring where Salesforce started before a developer org existed |

Real mode is not unit-tested at the `mcp_server` layer, matching the
existing convention for Jira/Slack/Calendar (see
`mcp_server/tests/conftest.py`): every tool here defaults to mock mode with
no real-mode HTTP mocking in the unit suite, relying on a real tenant and
manual verification for the live path.
