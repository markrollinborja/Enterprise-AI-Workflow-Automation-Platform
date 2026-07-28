from app.schemas import SendSlackNotificationInput
from app.tools.slack import execute_send_slack_notification


def test_mock_mode_returns_sent_status() -> None:
    result = execute_send_slack_notification(
        SendSlackNotificationInput(
            channel="#onboarding",
            message="Jamie Rivera's onboarding is complete.",
        )
    )
    assert result.status == "sent"
    assert result.channel == "#onboarding"
    assert result.message_ts  # non-empty, stands in for a real Slack ts
