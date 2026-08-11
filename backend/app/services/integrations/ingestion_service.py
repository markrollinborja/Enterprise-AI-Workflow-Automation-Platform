"""Inbound event ingestion — the front door for everything n8n sends us.

The flow is deliberately short: verify, record, acknowledge. Anything
expensive happens after the event is durably stored, so a slow downstream
step can never cause the sender to time out and retry a delivery we already
accepted.

Ordering matters and is not arbitrary. The event row is written *before* any
processing, because an event we failed to process is a support ticket while
an event we never recorded is a mystery. The support console can show a
FAILED row with its payload and a retry button; it cannot show something that
was dropped.
"""

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.correlation import ensure_correlation_id, get_correlation_id
from app.core.exceptions import AppError
from app.core.provider_errors import redact_mapping, summarize
from app.models.enums import InboundEventStatus, OrganizationStatus, ProviderType
from app.models.inbound_event import InboundEvent
from app.models.organization import Organization
from app.repositories import inbound_event_repo, organization_repo

logger = logging.getLogger(__name__)

# Event types this endpoint knows how to act on. An unrecognised type is
# recorded and acknowledged rather than rejected — a sender adding a new
# event type should not start receiving errors from us, and the row is the
# evidence that we saw something we did not understand.
ORGANIZATION_ONBOARDING_REQUESTED = "organization.onboarding_requested"

_SUPPORTED_EVENT_TYPES = frozenset({ORGANIZATION_ONBOARDING_REQUESTED})


class UnprocessableEventError(AppError):
    """The payload is well-formed JSON but missing what this event needs."""

    status_code = 422


def ingest_event(
    db: Session,
    *,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    correlation_id_from_caller: str | None = None,
    delivered_by: ProviderType = ProviderType.N8N,
    source_system: ProviderType = ProviderType.SALESFORCE,
) -> InboundEvent:
    """Record an inbound event and act on it if we know how.

    Never raises for a duplicate — that is a successful outcome (see
    InboundEventStatus.DUPLICATE). Raises only when the caller sent
    something this platform genuinely cannot accept.
    """
    # A correlation ID supplied in the body wins over the one the middleware
    # generated, because n8n minted it before it ever called us and its own
    # execution log records that value. Preferring ours would break the join
    # between the two systems, which is the entire point of the ID.
    correlation_id = (
        ensure_correlation_id(correlation_id_from_caller)
        if correlation_id_from_caller
        else get_correlation_id()
    )

    # Redacted at the boundary, before it is stored — the payload is
    # attacker-influenced and lands in a durable table the support console
    # renders.
    safe_payload = redact_mapping(payload)

    event, is_duplicate = inbound_event_repo.create_or_detect_duplicate(
        db,
        delivered_by=delivered_by,
        source_system=source_system,
        event_type=event_type,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=safe_payload,
    )

    log_context = {
        "event_type": event_type,
        "source_system": source_system.value,
        "idempotency_key": idempotency_key,
        "inbound_event_id": str(event.id),
    }

    if is_duplicate:
        # INFO, not WARNING. A provider retrying a delivery it never saw
        # acknowledged is behaving correctly; logging it as a warning trains
        # everyone to ignore warnings.
        logger.info(
            "Duplicate inbound event ignored",
            extra={**log_context, "duplicate_of": str(event.duplicate_of_id)},
        )
        return event

    if event_type not in _SUPPORTED_EVENT_TYPES:
        logger.warning("Unsupported inbound event type recorded", extra=log_context)
        return inbound_event_repo.mark_failed(
            db, event, error_summary=f"Unsupported event type: {event_type}"
        )

    try:
        organization = _ensure_organization(db, safe_payload)
    except UnprocessableEventError as exc:
        # Recorded as FAILED and re-raised: the caller gets a 422 so n8n can
        # route it to the failure-escalation workflow, and the row survives
        # so a human can see exactly what arrived.
        inbound_event_repo.mark_failed(db, event, error_summary=exc.message)
        logger.warning("Inbound event rejected as unprocessable", extra=log_context)
        raise
    except Exception as exc:
        inbound_event_repo.mark_failed(db, event, error_summary=summarize(exc))
        logger.exception("Inbound event processing failed", extra=log_context)
        raise

    logger.info(
        "Inbound event processed",
        extra={**log_context, "organization_id": str(organization.id)},
    )
    # No workflow instance yet — starting the organization onboarding
    # workflow is Phase 3's job, once the workflow definition and its
    # approval chain exist. The column is populated then; leaving it null
    # now is honest about what this phase actually does.
    return inbound_event_repo.mark_processed(db, event)


def _ensure_organization(db: Session, payload: dict[str, Any]) -> Organization:
    """Find or create the organization this event refers to.

    Idempotent by Salesforce Account ID via the external-identity mapping,
    so a repeated event for the same account updates rather than duplicates.
    """
    account = payload.get("account") or {}
    external_id = account.get("id")
    name = account.get("name")

    if not external_id or not name:
        raise UnprocessableEventError(
            "Event payload must include account.id and account.name"
        )

    existing = organization_repo.get_by_external_id(
        db, system=ProviderType.SALESFORCE, external_id=str(external_id)
    )
    if existing is not None:
        return existing

    return organization_repo.create_with_external_identity(
        db,
        name=str(name),
        slug=slugify(str(name)),
        primary_domain=_domain_from_website(account.get("website")),
        # ONBOARDING, not ACTIVE: the customer relationship exists but the
        # onboarding workflow has not run. Marking them ACTIVE here would
        # make the status field mean "we heard about them" rather than "they
        # are set up", which is the more useful meaning.
        status=OrganizationStatus.ONBOARDING,
        system=ProviderType.SALESFORCE,
        external_id=str(external_id),
    )


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """A URL-safe key derived from a name.

    Bounded and non-empty by construction: an organization named entirely in
    punctuation would otherwise produce an empty slug and violate the NOT
    NULL constraint at insert time, turning a naming oddity into a 500.
    """
    slug = _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")[:100]
    return slug or "organization"


def _domain_from_website(website: str | None) -> str | None:
    """Best-effort domain from a Salesforce Website field.

    Salesforce does not validate that field, so it arrives as anything from
    "cordant.io" to "www.cordant.io/contact" to nonsense. Extracting a
    domain rather than storing the raw string keeps later lookups (user
    email domain -> organization) meaningful, and returning None on anything
    unparseable is better than storing garbage that will never match.
    """
    if not website:
        return None
    cleaned = website.strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.split("/")[0]
    cleaned = cleaned.removeprefix("www.")
    return cleaned or None


def event_status_is_duplicate(event: InboundEvent) -> bool:
    return event.status is InboundEventStatus.DUPLICATE
