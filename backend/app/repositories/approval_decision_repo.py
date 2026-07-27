from typing import Any

from sqlalchemy.orm import Session

from app.models.approval import ApprovalDecision


def create(db: Session, **fields: Any) -> ApprovalDecision:
    decision = ApprovalDecision(**fields)
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision
