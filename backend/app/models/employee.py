import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import EmployeeStatus, EmploymentType, RiskLevel, enum_values

if TYPE_CHECKING:
    from app.models.department import Department


class Employee(Base):
    """The employee directory — separate from `User` (a login). Not every
    Employee has a User account (e.g. someone who hasn't been given system
    access, or never needs it — most rows here don't), and HR creates the
    Employee record before a login necessarily exists. See
    docs/architecture/data-model.md.

    `access_package_id` from the original data model isn't here yet — that
    FK points at AccessPackage, which doesn't exist until the AI
    recommendation feature (Phase 9) needs it. Same deferral pattern as
    User.employee_id in Phase 3: don't forward-declare a FK to a table
    nothing has built yet.
    """

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    work_email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Nullable, collected only when there's a reason: reaching someone before
    # their corporate account/email exists (offer letters, pre-boarding
    # logistics). Never populated in seed data beyond what's plausible.
    personal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("departments.id"), nullable=False
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id"), nullable=True
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        SAEnum(EmploymentType, name="employment_type", values_callable=enum_values),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[EmployeeStatus] = mapped_column(
        SAEnum(EmployeeStatus, name="employee_status", values_callable=enum_values),
        nullable=False,
        default=EmployeeStatus.ACTIVE,
    )
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, name="risk_level", values_callable=enum_values),
        nullable=False,
        default=RiskLevel.LOW,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    department: Mapped["Department"] = relationship(foreign_keys=[department_id])
    # Self-referential adjacency list: remote_side pins which column is the
    # "one" side, so SQLAlchemy doesn't try to guess for a FK pointing back
    # at the same table.
    manager: Mapped["Employee | None"] = relationship(remote_side=[id])
