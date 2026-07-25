from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check — the process is up. Does not touch the database.

    This is the one Docker/uptime checks should hit: it must stay fast and
    dependency-free so it never reports "down" just because Postgres is slow.
    """
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness check — the process is up AND can reach the database."""
    db.execute(text("SELECT 1"))
    return {"status": "ready"}
