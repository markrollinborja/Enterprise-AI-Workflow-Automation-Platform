"""send_slack_notification — used by both workflows' final step (onboarding's
notify_slack, the access request's notify_employee). Real mode uses
chat.postMessage with a bot token scoped to chat:write only — no broader
scope requested, per least-privilege (see integration-strategy.md)."""

import time

import httpx

from app.core.config import Settings, get_settings
from app.schemas import SendSlackNotificationInput, SendSlackNotificationOutput


def execute_send_slack_notification(
    input_data: SendSlackNotificationInput,
) -> SendSlackNotificationOutput:
    settings = get_settings()
    if settings.mcp_mock_mode:
        return _mock_send_slack_notification(input_data)
    return _real_send_slack_notification(input_data, settings)


def _mock_send_slack_notification(
    input_data: SendSlackNotificationInput,
) -> SendSlackNotificationOutput:
    return SendSlackNotificationOutput(
        message_ts=f"{time.time():.6f}",
        channel=input_data.channel,
        status="sent",
    )


def _real_send_slack_notification(
    input_data: SendSlackNotificationInput, settings: Settings
) -> SendSlackNotificationOutput:
    response = httpx.post(
        "https://slack.com/api/chat.postMessage",
        json={"channel": input_data.channel, "text": input_data.message},
        headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
        timeout=10.0,
    )
    response.raise_for_status()
    body = response.json()
    # Slack's API returns HTTP 200 even on failure (ok: false in the body)
    # — a real error here, not an httpx-raised exception, so it must be
    # checked explicitly rather than trusting raise_for_status() alone.
    if not body.get("ok", False):
        raise RuntimeError(f"Slack API error: {body.get('error', 'unknown error')}")
    return SendSlackNotificationOutput(
        message_ts=body["ts"],
        channel=body["channel"],
        status="sent",
    )
