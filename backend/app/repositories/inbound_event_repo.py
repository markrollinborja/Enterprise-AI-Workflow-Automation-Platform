from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import InboundEventStatus, ProviderType
from app.models.inbound_event import InboundEvent


def get_by_idempotency_key(db: Session, idempotency_key: str) -> InboundEvent | None:
    return db.scalars(
        select(InboundEvent).where(InboundEvent.idempotency_key == idempotency_key)
    ).first()


def get_by_id(db: Session, event_id: UUID) -> InboundEvent | None:
    return db.get(InboundEvent, event_id)


def create_or_detect_duplicate(
    db: Session,
    *,
    delivered_by: ProviderType,
    source_system: ProviderType,
    event_type: str,
    idempotency_key: str,
    correlation_id: str,
    payload: dict[str, Any],
) -> tuple[InboundEvent, bool]:
    """Insert the event, or detect that it is a duplicate.

    Returns `(event, is_duplicate)`.

    Written as insert-then-handle-IntegrityError rather than
    check-then-insert on purpose. A prior SELECT leaves a window in which
    two concurrent deliveries both find nothing and both insert — which is
    exactly the situation duplicate protection exists for, and exactly when
    it is most likely to happen (a provider retrying because the first
    attempt was slow). Letting Postgres arbitrate through the unique
    constraint closes that window, because only one transaction can win.
    """
    event = InboundEvent(
        delivered_by=delivered_by,
        source_system=source_system,
        event_type=event_type,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=payload,
        status=InboundEventStatus.RECEIVED,
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        original = get_by_idempotency_key(db, idempotency_key)
        if original is None:
            # The unique constraint fired but the original is not
            # visible — the only realistic cause is a different constraint
            # violation being misread as a duplicate. Re-raising beats
            # inventing a duplicate record that points at nothing.
            raise
        duplicate = InboundEvent(
            delivered_by=delivered_by,
            source_system=source_system,
            event_type=event_type,
            # Suffixed so the duplicate itself can be stored — the column is
            # unique, so a duplicate row cannot reuse the original key. The
            # link to the original is `duplicate_of_id`, not the key.
            idempotency_key=f"{idempotency_key}:dup:{datetime.now(UTC).timestamp()}",
            correlation_id=correlation_id,
            payload=payload,
            status=InboundEventStatus.DUPLICATE,
            duplicate_of_id=original.id,
            processed_at=datetime.now(UTC),
        )
        db.add(duplicate)
        db.commit()
        db.refresh(duplicate)
        return duplicate, True

    db.refresh(event)
    return event, False


def mark_processed(
    db: Session, event: InboundEvent, *, workflow_instance_id: UUID | None = None
) -> InboundEvent:
    event.status = InboundEventStatus.PROCESSED
    event.workflow_instance_id = workflow_instance_id
    event.processed_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return event


def mark_failed(db: Session, event: InboundEvent, *, error_summary: str) -> InboundEvent:
    event.status = InboundEventStatus.FAILED
    event.error_summary = error_summary
    event.processed_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return event


def find_by_correlation_id(db: Session, correlation_id: str) -> list[InboundEvent]:
    """Every event under one correlation ID — the support console's primary
    lookup (Module 8)."""
    return list(
        db.scalars(
            select(InboundEvent)
            .where(InboundEvent.correlation_id == correlation_id)
            .order_by(InboundEvent.received_at.desc())
        )
    )


def list_recent(db: Session, *, limit: int = 50) -> list[InboundEvent]:
    return list(
        db.scalars(select(InboundEvent).order_by(InboundEvent.received_at.desc()).limit(limit))
    )
