"""The access-package catalog the AI recommends *from* — never invents a
grant from scratch (Principle 2, "rules before AI"; see
services/ai/service.py's dynamic enum constraint, which makes this a
structural guarantee, not just a prompt instruction). Modeled the same way
as Application: internal reference data, seeded, no external source.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import RiskLevel, enum_values

if TYPE_CHECKING:
    from app.models.department import Department


class AccessPackage(Base):
    __tablename__ = "access_packages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Nullable — a handful of packages are cross-department (e.g. a generic
    # "Standard" package) rather than owned by one specific department.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("departments.id"), nullable=True
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, name="risk_level", values_callable=enum_values),
        nullable=False,
    )
    # Plain list of system/tool names included in the package (e.g.
    # ["Slack", "GitHub", "AWS Console"]) — descriptive, not a live FK to
    # Application; nothing cross-references those rows against Application.id
    # in V1, so a normalized join table would add a join for no capability.
    included_systems: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    department: Mapped["Department | None"] = relationship()
