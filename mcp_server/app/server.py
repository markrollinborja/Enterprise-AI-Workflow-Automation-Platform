"""The real MCP server process (ADR-0005) — FastMCP over streamable-HTTP
transport, not an in-process module the backend imports. The backend and
the AI service connect to this as MCP *clients*, over the network (see
backend/app/services/integrations/mcp_client.py) — crossing an actual
protocol boundary is the whole point (see docs/architecture/mcp-architecture.md).

Each @mcp.tool()-decorated function here takes flat, individually
type-hinted parameters (matching every example in the SDK's own docs —
`add(a: int, b: int)`, not `add(input: AddInput)`) so the JSON schema a
caller sees is flat too: `{"project_key": ..., "summary": ...}`, not a
value nested under one wrapper key. Each wrapper immediately builds the
real Pydantic input model and delegates to a plain, directly-unit-tested
`execute_*` function in app/tools/ — the validation and business logic
live there, not in the wrapper.
"""

from typing import Literal

from mcp.server.fastmcp import FastMCP

from app.schemas import (
    CreateJiraTaskInput,
    CreateJiraTaskOutput,
    ScheduleCalendarEventInput,
    ScheduleCalendarEventOutput,
    SendSlackNotificationInput,
    SendSlackNotificationOutput,
)
from app.tools.calendar import execute_schedule_calendar_event
from app.tools.jira import execute_create_jira_task
from app.tools.slack import execute_send_slack_notification

# host/port go on the constructor, not run(transport=...) — confirmed via
# mypy against the actually-installed mcp==1.9.4 that FastMCP.run() at this
# pin doesn't accept them as keyword arguments (some SDK versions do; this
# one doesn't — see ADR-0012's note on this SDK's version-to-version
# drift). Port 8100 matches docker-compose.yml and Settings.mcp_server_url.
mcp = FastMCP("Meridian Flow MCP Server", host="0.0.0.0", port=8100)


@mcp.tool()
def create_jira_task(
    project_key: str,
    summary: str,
    description: str,
    issue_type: Literal["Task", "Story"] = "Task",
    assignee_email: str | None = None,
) -> CreateJiraTaskOutput:
    """Create a Jira issue for an onboarding or access-request fulfillment
    task. Caller supplies the project, summary, description, and issue
    type — this tool does not decide what task to create, only creates it."""
    return execute_create_jira_task(
        CreateJiraTaskInput(
            project_key=project_key,
            summary=summary,
            description=description,
            issue_type=issue_type,
            assignee_email=assignee_email,
        )
    )


@mcp.tool()
def send_slack_notification(channel: str, message: str) -> SendSlackNotificationOutput:
    """Post a message to a Slack channel. Uses a bot token scoped to
    chat:write only — this tool cannot read channel history, manage users,
    or do anything beyond sending the one message it's given."""
    return execute_send_slack_notification(
        SendSlackNotificationInput(channel=channel, message=message)
    )


@mcp.tool()
def schedule_calendar_event(
    summary: str,
    description: str,
    start_time_iso: str,
    duration_minutes: int = 30,
    attendee_emails: list[str] | None = None,
) -> ScheduleCalendarEventOutput:
    """Create an event on the shared Meridian Flow demo calendar (a service
    account, not a real employee's personal calendar) — used for new-hire
    orientation scheduling."""
    return execute_schedule_calendar_event(
        ScheduleCalendarEventInput(
            summary=summary,
            description=description,
            start_time_iso=start_time_iso,
            duration_minutes=duration_minutes,
            attendee_emails=attendee_emails or [],
        )
    )


# lookup_employee is added here in Phase 10 checkpoint 2 (app/tools/employee.py)
# once the AI service's agentic tool-calling loop is built to actually call it.


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
