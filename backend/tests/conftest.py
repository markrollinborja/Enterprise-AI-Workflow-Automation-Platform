import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.main import app
from app.models.approval import ApprovalDecision, ApprovalRequest
from app.models.department import Department
from app.models.employee import Employee
from app.models.user import User
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowInstance,
    WorkflowStepInstance,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session():
    """Yields a real session against the test database (see DATABASE_URL in
    CI / your local .env). Cleans up test-created rows after each test —
    simple and correct for a handful of tables; Phase 14 can move to
    transaction-rollback isolation once there are many more.

    Deletion order matters here: users.employee_id and Employee's own
    self-referential manager_id both need clearing before the rows they
    point at can be deleted, or Postgres rejects the delete on an FK
    violation — nulling both out first sidesteps having to compute a safe
    delete order by hand. ApprovalDecision and ApprovalRequest (FK to
    workflow/step instances and users) go first, then WorkflowEvent, then
    step/instance rows, before employees/users themselves;
    workflow_definitions has no such dependency so it can go last.
    """
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.execute(delete(ApprovalDecision))
        session.execute(delete(ApprovalRequest))
        session.execute(delete(WorkflowEvent))
        session.execute(delete(WorkflowStepInstance))
        session.execute(delete(WorkflowInstance))
        session.execute(update(User).values(employee_id=None))
        session.execute(delete(User))
        session.execute(update(Employee).values(manager_id=None))
        session.execute(delete(Employee))
        session.execute(delete(Department))
        session.execute(delete(WorkflowDefinition))
        session.commit()
        session.close()
