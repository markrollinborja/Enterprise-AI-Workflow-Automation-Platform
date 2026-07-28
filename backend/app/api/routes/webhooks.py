"""Inbound webhook endpoints — currently just Jira's fulfillment
confirmation (ADR-0010). No parallel to Project #1's Jira webhook despite
the same route name: there, a Jira webhook *is* the trigger that starts
the whole automation; here, it closes the loop on a ticket this system
already created as one step inside a larger, already-orchestrated,
multi-department workflow — confirmation of fulfillment, not the
initiating event. See ADR-0010's "also worth naming directly" note.

Unauthenticated in the normal (JWT bearer) sense — Jira can't hold a user
session with this system — but not unauthenticated in the security sense:
every request must carry a valid HMAC-SHA256 signature over the raw body,
computed with the shared secret configured on the Jira webhook itself
(JIRA_WEBHOOK_SECRET). See _verify_signature.
"""

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import InvalidWebhookSignatureError
from app.db.session import get_db
from app.models.enums import InstanceStatus, StepStatus
from app.repositories import workflow_instance_repo, workflow_step_repo
from app.services.workflows.service import confirm_external_completion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Only this status transition is treated as fulfillment (see ADR-0010's
# scope note) — any other Jira status update on a tracked issue is
# acknowledged and ignored, not an error.
_FULFILLMENT_STATUS = "done"


@router.post("/jira")
async def jira_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Every response path below is 2xx except signature failure — a
    webhook endpoint that 4xx/5xxs a *duplicate* or *irrelevant* delivery
    just trains the sender to keep retrying it. The only genuinely
    exceptional outcome from Jira's point of view is "I couldn't verify
    this request came from you," which is what actually warrants a
    non-2xx.
    """
    raw_body = await request.body()
    settings = get_settings()
    signature = request.headers.get("x-hub-signature-256") or request.headers.get(
        "x-hub-signature"
    )
    if not settings.jira_webhook_secret or not _verify_signature(
        raw_body, signature, settings.jira_webhook_secret
    ):
        raise InvalidWebhookSignatureError("Could not verify this request came from Jira.")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {"status": "ignored", "reason": "malformed JSON payload"}

    issue_key, status_name = _extract_issue_status(payload)
    if issue_key is None or status_name is None:
        return {"status": "ignored", "reason": "not a recognizable issue status update"}
    if status_name.strip().lower() != _FULFILLMENT_STATUS:
        return {
            "status": "ignored",
            "reason": f"status '{status_name}' is not a fulfillment state",
        }

    step_row = workflow_step_repo.get_by_external_ref(db, issue_key)
    if step_row is None:
        # Expected, not an error: a Jira webhook is normally scoped to a
        # whole project, so most issue updates it delivers won't correlate
        # to anything this system is tracking at all.
        return {"status": "ignored", "reason": "no workflow step tracking this issue"}
    if step_row.status != StepStatus.WAITING_EXTERNAL:
        # Expected on a duplicate delivery (Jira retries webhooks) — the
        # first delivery already confirmed this step. Also covers "this
        # issue key was tracked in the past but that step has since moved
        # on some other way," which shouldn't happen in V1 but degrades
        # safely if it ever does.
        return {
            "status": "ignored",
            "reason": f"step already in status '{step_row.status.value}'",
        }

    instance = workflow_instance_repo.get_by_id(db, step_row.workflow_instance_id)
    if instance is None or instance.status != InstanceStatus.WAITING_EXTERNAL:
        return {"status": "ignored", "reason": "workflow instance is not awaiting confirmation"}

    confirm_external_completion(db, instance, step_row)
    logger.info("Jira fulfillment confirmed for issue %s (step %s)", issue_key, step_row.id)
    return {"status": "confirmed", "issue_key": issue_key}


def _verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Jira Cloud signs dynamic-webhook (REST-API-registered) payloads with
    HMAC-SHA256 over the exact raw request bytes, sent as
    `X-Hub-Signature-256: sha256=<hex digest>` (WebSub-style, added to Jira
    Cloud Feb 2024) — the same shape as verifying a GitHub or Stripe
    webhook. hmac.compare_digest, not `==`, so this doesn't leak timing
    information about how much of the signature matched."""
    if not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header[len(prefix) :]
    return hmac.compare_digest(expected, provided)


def _extract_issue_status(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pulls (issue_key, status_name) out of a Jira `jira:issue_updated`
    webhook payload's well-known shape
    (`issue.key`, `issue.fields.status.name`). Defensive `.get()` chains
    rather than direct indexing — any other Jira webhook event type, or a
    malformed/unexpected payload, should degrade to "ignored," never a
    500."""
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return None, None
    issue_key = issue.get("key")
    fields = issue.get("fields")
    status = fields.get("status") if isinstance(fields, dict) else None
    status_name = status.get("name") if isinstance(status, dict) else None
    if not isinstance(issue_key, str) or not isinstance(status_name, str):
        return None, None
    return issue_key, status_name
