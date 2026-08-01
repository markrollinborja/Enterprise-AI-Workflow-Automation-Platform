"""create_jira_task — the one Jira-creation tool both V1 workflows use
(onboarding's create_it_tasks step, the access-request workflow's
create_fulfillment_task step). One generic tool, not two near-duplicate
ones named after each workflow — see ADR-0012's naming note; which Jira
project/summary/description to send is decided by the *caller*
(backend/app/services/workflows/executors.py), not by this tool guessing
which workflow it's being called from.

execute_create_jira_task is the plain, directly-testable function —
server.py wraps it with @mcp.tool() so the MCP-decorated function and the
unit-tested function are the same code, not a thin wrapper hiding untested
logic.
"""

import uuid

import httpx

from app.core.config import Settings, get_settings
from app.schemas import CreateJiraTaskInput, CreateJiraTaskOutput


def execute_create_jira_task(input_data: CreateJiraTaskInput) -> CreateJiraTaskOutput:
    settings = get_settings()
    if settings.mcp_mock_mode:
        return _mock_create_jira_task(input_data)
    return _real_create_jira_task(input_data, settings)


def _mock_create_jira_task(input_data: CreateJiraTaskInput) -> CreateJiraTaskOutput:
    # A realistic-looking, well-formed fake issue key — not "MOCK-1" —
    # so downstream code (the webhook correlation in Phase 10 checkpoint 3,
    # the dashboard in Phase 12) sees the same shape it would in real mode.
    fake_key = f"{input_data.project_key}-{uuid.uuid4().int % 9000 + 1000}"
    return CreateJiraTaskOutput(
        issue_key=fake_key,
        issue_url=f"https://mock-jira.example.com/browse/{fake_key}",
        status="created",
    )


def _real_create_jira_task(
    input_data: CreateJiraTaskInput, settings: Settings
) -> CreateJiraTaskOutput:
    """Real mode: Jira Cloud REST API v3 issue creation, basic auth (email +
    API token). Raises on any failure — the caller (services/integrations/
    mcp_client.py) is responsible for catching and turning that into a
    failed MCPToolExecution row and a failed StepExecutionResult; this
    function's job is only to make the real call and report a real error,
    not to swallow one."""
    payload = {
        "fields": {
            "project": {"key": input_data.project_key},
            "summary": input_data.summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": input_data.description}],
                    }
                ],
            },
            "issuetype": {"name": input_data.issue_type},
            **(
                {"assignee": {"emailAddress": input_data.assignee_email}}
                if input_data.assignee_email
                else {}
            ),
        }
    }
    response = httpx.post(
        f"{settings.jira_base_url}/rest/api/3/issue",
        json=payload,
        auth=(settings.jira_email, settings.jira_api_token),
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # response.raise_for_status()'s own message is just "400 Bad
        # Request for url ..." — it never includes the response body, which
        # is exactly where Jira puts the actual reason (e.g. "issuetype":
        # "Task" isn't valid for this project, a required field is
        # missing, ...). Re-raising with the body included is the
        # difference between an actionable error and a dead end.
        raise RuntimeError(
            f"Jira API error {exc.response.status_code}: {exc.response.text}"
        ) from exc
    body = response.json()
    issue_key = body["key"]
    return CreateJiraTaskOutput(
        issue_key=issue_key,
        issue_url=f"{settings.jira_base_url}/browse/{issue_key}",
        status="created",
    )
