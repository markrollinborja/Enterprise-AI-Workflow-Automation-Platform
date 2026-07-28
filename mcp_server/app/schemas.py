"""Typed input/output for every MCP tool this server exposes. One file, not
one per tool, because these are small and it's the single place to see the
whole tool surface at a glance — see mcp-architecture.md's tool table.

FastMCP derives each tool's JSON schema from the decorated function's own
type-hinted parameters and return annotation (see server.py) — these
classes are used directly as that signature, not translated into a separate
manually-written schema.
"""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class CreateJiraTaskInput(BaseModel):
    project_key: str = Field(description="Jira project key, e.g. 'ONB' or 'ACC'.")
    summary: str = Field(description="Issue summary/title.")
    description: str = Field(description="Issue description body.")
    issue_type: Literal["Task", "Story"] = "Task"
    assignee_email: EmailStr | None = Field(
        default=None, description="Email of the Jira user to assign, if known."
    )


class CreateJiraTaskOutput(BaseModel):
    issue_key: str
    issue_url: str
    status: Literal["created", "failed"]


class SendSlackNotificationInput(BaseModel):
    channel: str = Field(description="Slack channel name or ID, e.g. '#onboarding'.")
    message: str = Field(description="Message text to post.")


class SendSlackNotificationOutput(BaseModel):
    message_ts: str = Field(description="Slack message timestamp, used as the message ID.")
    channel: str
    status: Literal["sent", "failed"]


class ScheduleCalendarEventInput(BaseModel):
    summary: str = Field(description="Event title.")
    description: str = Field(description="Event description body.")
    start_time_iso: str = Field(
        description="Event start time, ISO 8601 (e.g. '2026-08-01T09:00:00Z')."
    )
    duration_minutes: int = Field(default=30, ge=5, le=480)
    attendee_emails: list[EmailStr] = Field(default_factory=list)


class ScheduleCalendarEventOutput(BaseModel):
    event_id: str
    event_url: str
    status: Literal["scheduled", "failed"]
