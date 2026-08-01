"""schedule_calendar_event — used by onboarding's schedule_orientation step
only (the access-request workflow has no calendar step). Real mode uses a
Google service account with access to one shared "Meridian Flow Demo"
calendar, not per-user OAuth — see integration-strategy.md for why:
per-user consent/refresh-token management is real-product complexity this
project doesn't need to prove.
"""

import json
import uuid
from datetime import datetime, timedelta

from app.core.config import Settings, get_settings
from app.schemas import ScheduleCalendarEventInput, ScheduleCalendarEventOutput


def execute_schedule_calendar_event(
    input_data: ScheduleCalendarEventInput,
) -> ScheduleCalendarEventOutput:
    settings = get_settings()
    if settings.mcp_mock_mode:
        return _mock_schedule_calendar_event(input_data)
    return _real_schedule_calendar_event(input_data, settings)


def _mock_schedule_calendar_event(
    input_data: ScheduleCalendarEventInput,
) -> ScheduleCalendarEventOutput:
    fake_id = uuid.uuid4().hex[:26]  # roughly Google Calendar's real ID shape
    return ScheduleCalendarEventOutput(
        event_id=fake_id,
        event_url=f"https://calendar.google.com/calendar/event?eid={fake_id}",
        status="scheduled",
    )


def _real_schedule_calendar_event(
    input_data: ScheduleCalendarEventInput, settings: Settings
) -> ScheduleCalendarEventOutput:
    # Imported lazily: these two packages are only needed in real mode, and
    # only mock mode is exercised in CI/tests (see tests/conftest.py) — no
    # reason to make the whole server fail to import if a dev environment
    # is missing them, or to pay their import cost on every mock-mode call.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials_info = json.loads(settings.google_calendar_credentials_json)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    service = build("calendar", "v3", credentials=credentials)

    start_time = datetime.fromisoformat(input_data.start_time_iso.replace("Z", "+00:00"))
    end_time = start_time + timedelta(minutes=input_data.duration_minutes)

    # No "attendees" field: a bare service account (no Google Workspace
    # domain-wide delegation — which needs a paid Workspace admin console,
    # ruled out by this project's free-tier constraint) is not permitted to
    # invite attendees to an event at all; Google returns a 403
    # ("forbiddenForServiceAccounts") on every attempt, so retrying never
    # helps. The event itself is still created for real — attendee_emails
    # is folded into the description instead of lost, since there's no
    # invite mechanism available to deliver it any other way.
    description = input_data.description
    if input_data.attendee_emails:
        description = f"{description}\n\nAttendee(s): {', '.join(input_data.attendee_emails)}"
    event_body = {
        "summary": input_data.summary,
        "description": description,
        "start": {"dateTime": start_time.isoformat()},
        "end": {"dateTime": end_time.isoformat()},
    }
    created = (
        service.events()
        .insert(calendarId=settings.google_calendar_id, body=event_body)
        .execute()
    )
    return ScheduleCalendarEventOutput(
        event_id=created["id"],
        event_url=created.get("htmlLink", ""),
        status="scheduled",
    )
