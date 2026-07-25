from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy models.

    No models yet — the first ones (Employee, Department, User, ...) land in
    Phase 4. This file exists now so Alembic has a stable target to import.
    """
