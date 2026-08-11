"""Inbound integration events — the endpoint n8n calls.

Separate from V1's `webhooks.py` (Jira fulfillment confirmation) on purpose.
That route closes the loop on a ticket this system already created; this one
*opens* a transaction from outside. Different trust model, different failure
handling, different reader — keeping them apart means neither has to carry
comments explaining which paragraph applies to it.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.webhook_security import verify_hmac_signature
from app.db.session import get_db
from app.models.enums import InboundEventStatus, UserRole
from app.models.user import User
from app.repositories import inbound_event_repo
from app.schemas.inbound_event import InboundEventResponse
from app.services.integrations import ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbound", tags=["inbound-events"])

MAX_PAYLOAD_BYTES = 256 * 1024


class MalformedEventError(AppError):
    """The request body is not usable JSON, or is missing required headers."""

    status_code = 400


class PayloadTooLargeError(AppError):
    status_code = 413


@router.post("/events", response_model=InboundEventResponse)
async def receive_event(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    x_event_type: str | None = Header(default=None, alias="X-Event-Type"),
) -> InboundEventResponse:
    """Accept one normalized event from n8n.

    HMAC-verified, not JWT-authenticated: n8n is a service, not a user, and
    cannot hold a session. Signature verification happens against the raw
    body before anything is parsed — deserializing an unverified payload
    means running a parser on attacker-controlled input, which is exactly
    the code you least want to reach first.

    Returns 200 for a duplicate as well as a first delivery. A sender
    retrying because it never saw our acknowledgement is behaving correctly,
    and answering with an error would push a well-behaved integration into
    its failure path.
    """
    raw_body = await request.body()

    if len(raw_body) > MAX_PAYLOAD_BYTES:
        # Checked before signature verification: HMAC over an unbounded body
        # is an easy way to burn CPU on a request that was never going to be
        # accepted.
        raise PayloadTooLargeError("Event payload exceeds the maximum accepted size")

    settings = get_settings()
    verify_hmac_signature(
        raw_body=raw_body,
        provided_signature=x_signature,
        secret=settings.n8n_webhook_secret,
        caller="n8n",
    )

    if not x_idempotency_key:
        # Required, not derived from the payload. A sender that cannot
        # produce a stable key cannot be protected against duplicates, and
        # inventing one here (hashing the body) would silently treat two
        # legitimately identical events as one.
        raise MalformedEventError("X-Idempotency-Key header is required")

    if not x_event_type:
        raise MalformedEventError("X-Event-Type header is required")

    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except ValueError as exc:
        raise MalformedEventError(f"Request body is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MalformedEventError("Request body must be a JSON object")

    event = ingestion_service.ingest_event(
        db,
        event_type=x_event_type,
        idempotency_key=x_idempotency_key,
        payload=payload,
        correlation_id_from_caller=payload.get("correlation_id"),
    )

    # 200 for a first delivery, 208 Already Reported for a duplicate. Both
    # are success; the distinct code lets n8n's own logs show at a glance
    # that a retry was recognised, without having to parse the body.
    if event.status is InboundEventStatus.DUPLICATE:
        response.status_code = 208

    return InboundEventResponse.model_validate(event)


@router.get("/events", response_model=list[InboundEventResponse])
def list_events(
    limit: int = 50,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(UserRole.IT, UserRole.SECURITY, UserRole.ADMINISTRATOR)),
) -> list[InboundEventResponse]:
    """Recent inbound events — the raw material for the support console."""
    events = inbound_event_repo.list_recent(db, limit=min(limit, 200))
    return [InboundEventResponse.model_validate(e) for e in events]


@router.get("/events/by-correlation/{correlation_id}", response_model=list[InboundEventResponse])
def get_events_by_correlation(
    correlation_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(UserRole.IT, UserRole.SECURITY, UserRole.ADMINISTRATOR)),
) -> list[InboundEventResponse]:
    """Everything that arrived under one correlation ID.

    The support console's primary lookup: paste the ID out of a Slack alert
    and see the whole transaction.
    """
    events = inbound_event_repo.find_by_correlation_id(db, correlation_id)
    return [InboundEventResponse.model_validate(e) for e in events]
