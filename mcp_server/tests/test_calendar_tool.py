from app.schemas import ScheduleCalendarEventInput
from app.tools.calendar import execute_schedule_calendar_event


def test_mock_mode_returns_scheduled_status() -> None:
    result = execute_schedule_calendar_event(
        ScheduleCalendarEventInput(
            summary="Orientation: Jamie Rivera",
            description="New hire orientation session.",
            start_time_iso="2026-08-01T09:00:00Z",
            duration_minutes=60,
            attendee_emails=["jamie.rivera@cordant.io", "hr@cordant.io"],
        )
    )
    assert result.status == "scheduled"
    assert result.event_id
    assert result.event_url


def test_mock_mode_works_with_no_attendees() -> None:
    result = execute_schedule_calendar_event(
        ScheduleCalendarEventInput(
            summary="Orientation",
            description="No attendees listed yet.",
            start_time_iso="2026-08-01T09:00:00Z",
        )
    )
    assert result.status == "scheduled"
