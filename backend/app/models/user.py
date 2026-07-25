import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import UserRole


class User(Base):
    """Auth identity. Deliberately has no `employee_id` yet — the Employee
    table doesn't exist until Phase 4. That column is added in a Phase 4
    migration once there's something for it to reference, instead of
    forward-declaring a FK to a table that doesn't exist yet."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # values_callable is required here: SQLAlchemy's default behavior for a
    # Python str Enum is to persist the member's *name* ("HR"), not its
    # *value* ("hr") — but the Postgres enum type (see the migration) only
    # accepts the lowercase values. Without this, every insert fails with
    # "invalid input value for enum user_role". Apply this same pattern to
    # every future Enum column (Employee status, etc. in Phase 4+).
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
