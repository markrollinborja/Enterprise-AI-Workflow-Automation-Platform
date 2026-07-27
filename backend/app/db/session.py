from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# prepare_threshold=None disables psycopg3's server-side prepared-statement
# caching (its default: auto-prepare a query after its 5th execution on a
# given connection). Diagnosing a flaky test failure — a state-machine
# self-transition error that only appeared once enough prior queries had run
# on the same pooled connection, and which specific test tripped it varied
# between runs — this is the leading suspect: enough repeated same-shaped
# UPDATE statements (writing WorkflowInstance/WorkflowStepInstance.status)
# crossing that threshold on a reused connection. Not confirmed with 100%
# certainty, but disabling it is safe (only turns off a query-plan caching
# optimization, changes no behavior) and directly testable.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"prepare_threshold": None},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
