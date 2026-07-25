import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.user import User


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session():
    """Yields a real session against the test database (see DATABASE_URL in
    CI / your local .env). Cleans up by deleting test-created users after
    each test — simple and correct for one table; Phase 14 can move to
    transaction-rollback isolation once there are many tables to reset."""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.execute(delete(User))
        session.commit()
        session.close()
