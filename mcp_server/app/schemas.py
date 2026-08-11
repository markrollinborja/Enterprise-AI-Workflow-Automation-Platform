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


class ProvisionM365AccountInput(BaseModel):
    display_name: str = Field(description="Full name for the Microsoft 365 account.")
    user_principal_name: EmailStr = Field(
        description="UPN / sign-in address, e.g. 'jane.doe@cordant.io'."
    )
    job_title: str = Field(description="Job title, set on the account for directory lookups.")
    department: str = Field(description="Department name, set on the account.")


class ProvisionM365AccountOutput(BaseModel):
    m365_user_id: str = Field(description="The account's Entra ID object ID (a GUID).")
    user_principal_name: str
    status: Literal["created", "failed"]
    # See docs/architecture/microsoft-graph.md and ADR-0020: this platform
    # provisions through the Graph API directly (or simulates doing so) and
    # *also* always returns the PowerShell an IT admin would run to
    # reproduce or verify the same action by hand — a generated artifact
    # for review, never something this tool executes itself. Present in
    # both mock and live mode, identically, so the audit trail looks the
    # same regardless of which mode produced it.
    powershell_script: str


class LookupEmployeeInput(BaseModel):
    employee_id: str = Field(description="Employee UUID, as a string.")


class LookupEmployeeOutput(BaseModel):
    """No mock-mode counterpart (contrast with the three tools above) —
    this reads Meridian Flow's own database, not an external SaaS, so
    there's nothing to simulate. `found=False` (all other fields None) is
    the normal, expected shape for an unknown or malformed ID — a business
    outcome the caller (the AI agent's tool-calling loop) is expected to
    handle, not a tool failure. Real failures (the database being
    unreachable) still propagate as an MCP tool error."""

    found: bool
    employee_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    work_email: str | None = None
    job_title: str | None = None
    department_name: str | None = None
    employment_type: str | None = None
    status: str | None = None
    risk_level: str | None = None
