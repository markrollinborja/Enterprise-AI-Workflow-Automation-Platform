"""notifications — writes Notification rows and, for channels beyond
in-app, delegates the actual send. Reserved in Phase 1's data-model
sketch, built for real in Phase 11. Only ever called from
services/workflows/service.py, at the three points an event that matters
to a specific person actually happens (see NotificationType) — never from
a route directly, and never decides *whether* an event is notification-
worthy itself (that judgment call lives in the caller).

One row per (event, channel) — see NotificationChannel's own docstring.
`notify()` always writes the IN_APP row; SLACK/EMAIL are opt-in per call
via `send_slack`/`send_email`, not automatic for every event, matching how
a real system wouldn't push every notification through every channel:

- APPROVAL_REQUESTED: in-app + Slack. Someone needs to act now — the one
  case in V1 where an interruption is warranted (see ADR-0010-adjacent
  reasoning: Slack is for "act now," not "here's a status update").
- WORKFLOW_COMPLETED: in-app only. A status update, not urgent.
- WORKFLOW_REJECTED: in-app + email (simulated). Bad news a submitter
  should see even if they're not actively watching the dashboard —
  demonstrates the email channel is real, not decorative, without needing
  a third "when to interrupt" judgment call to also justify Slack here.

A failed Slack send never blocks the in-app row or raises — this mirrors
the workflow engine's own notify_slack step (failure_behavior=continue): a
missed Slack ping is not a reason to fail anything. Email is simulated
(formatted + logged + written as its own row), so it cannot fail in V1 —
there's no real transport to fail.
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import (
    MCPToolCaller,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.models.user import User
from app.repositories import notification_repo
from app.schemas.notification import NotificationResponse
from app.services.integrations import mcp_client
from app.services.integrations.mcp_client import MCPToolError

logger = logging.getLogger(__name__)


def notify(
    db: Session,
    *,
    recipient: User | None,
    notification_type: NotificationType,
    title: str,
    body: str,
    workflow_instance_id: UUID | None = None,
    step_instance_id: UUID | None = None,
    send_slack: bool = False,
    send_email: bool = False,
) -> None:
    """The one entry point every trigger in services/workflows/service.py
    calls. `recipient=None` is a deliberate, silent no-op, not an error —
    an onboarding instance's new hire often has no User login yet, and a
    notification with nowhere to go isn't a failure, just nothing to do.
    """
    if recipient is None:
        return

    notification_repo.create(
        db,
        user_id=recipient.id,
        workflow_instance_id=workflow_instance_id,
        type=notification_type,
        title=title,
        body=body,
        channel=NotificationChannel.IN_APP,
        status=NotificationStatus.COMPLETED,
    )

    if send_slack:
        _send_slack(
            db,
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            workflow_instance_id=workflow_instance_id,
            step_instance_id=step_instance_id,
        )

    if send_email:
        _simulate_email(
            db,
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            body=body,
            workflow_instance_id=workflow_instance_id,
        )


def list_for_user(db: Session, user: User) -> list[NotificationResponse]:
    """The in-app notification list a user sees. Every authenticated user
    can call this — like approvals' list_pending_for_user, the filtering
    (own user_id, IN_APP channel only) IS the access control, done in
    notification_repo.list_for_user."""
    return [
        NotificationResponse.model_validate(n)
        for n in notification_repo.list_for_user(db, user.id)
    ]


def mark_read(db: Session, notification_id: UUID, user: User) -> NotificationResponse:
    """Raises NotFoundError both when the row doesn't exist and when it
    belongs to someone else — same reasoning as InvalidWebhookSignatureError
    covering two failure modes with one response: a caller probing other
    users' notification IDs shouldn't be able to tell "not mine" from
    "doesn't exist" from the response."""
    notification = notification_repo.get_by_id(db, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFoundError("Notification not found.")
    return NotificationResponse.model_validate(notification_repo.mark_read(db, notification))


def _send_slack(
    db: Session,
    *,
    recipient: User,
    notification_type: NotificationType,
    title: str,
    body: str,
    workflow_instance_id: UUID | None,
    step_instance_id: UUID | None,
) -> None:
    """Real send, through the same send_slack_notification MCP tool the
    workflow engine's own scripted steps use — via mcp_client.py, so this
    is audited in MCPToolExecution exactly like any other Slack call, not
    a side channel that bypasses that audit trail (see
    docs/architecture/service-boundaries.md's "notifications" section:
    "Does not call Slack directly")."""
    # Same real-mode limitation already noted in executors.py's
    # notify_employee: Slack DM addressing needs a user ID, not an email;
    # real mode would need a users.lookupByEmail call first. Mock mode
    # doesn't care. Known V1 gap, not a bug.
    channel_name = f"@{recipient.email}"
    try:
        mcp_client.call_tool(
            db,
            tool_name="send_slack_notification",
            arguments={"channel": channel_name, "message": f"{title}\n{body}"},
            caller=MCPToolCaller.WORKFLOW_ENGINE,
            workflow_instance_id=workflow_instance_id,
            step_instance_id=step_instance_id,
        )
        status = NotificationStatus.COMPLETED
    except MCPToolError:
        # mcp_client.py already wrote the failed MCPToolExecution row —
        # this is a second, notifications-scoped record of the same
        # failure (Principle 4: "integration failed" is its own row),
        # never re-raised.
        status = NotificationStatus.FAILED

    notification_repo.create(
        db,
        user_id=recipient.id,
        workflow_instance_id=workflow_instance_id,
        type=notification_type,
        title=title,
        body=body,
        channel=NotificationChannel.SLACK,
        status=status,
    )


def _simulate_email(
    db: Session,
    *,
    recipient: User,
    notification_type: NotificationType,
    title: str,
    body: str,
    workflow_instance_id: UUID | None,
) -> None:
    """No SMTP/Gmail integration in V1 (matches the project's non-goals) —
    this formats and logs what would be sent, then writes the row. The row
    is the actual artifact; there is no external call here to audit in
    MCPToolExecution, since nothing left this process."""
    logger.info("Simulated email to %s: %s — %s", recipient.email, title, body)
    notification_repo.create(
        db,
        user_id=recipient.id,
        workflow_instance_id=workflow_instance_id,
        type=notification_type,
        title=title,
        body=body,
        channel=NotificationChannel.EMAIL,
        status=NotificationStatus.COMPLETED,
    )
