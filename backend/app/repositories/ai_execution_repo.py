from typing import Any

from sqlalchemy.orm import Session

from app.models.ai_execution import AIExecution


def create(db: Session, **fields: Any) -> AIExecution:
    """No get/list helpers yet — nothing reads AIExecution rows back in V1
    (Phase 12's dashboard is the first planned consumer, per data-model.md).
    Not adding unused query methods ahead of a real caller — same discipline
    as Application.owner_role and Employee.access_package_id (ADR-0009)."""
    execution = AIExecution(**fields)
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution
