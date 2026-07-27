"""The application catalog — internal reference data describing each
software system employees can request access to. Modeled the same way as
`Department`: a plain internal table, not wrapped behind MCP and not
sourced from an external identity provider. See
docs/decisions/0009-application-catalog-internal-not-okta.md for why V1
doesn't integrate a real IdP (e.g. Okta) to source this catalog, and
docs/architecture/mcp-architecture.md for why MCP is reserved for genuine
external actions (Jira, Slack, Calendar) rather than decoration around a
deterministic internal lookup.

`owner_role` was in the original Phase 1 sketch (see data-model.md's
revision history) but is deliberately not a column here — nothing in Phase
8 reads it. Every `it_approval` step routes to role=IT and every
`security_approval` step routes to role=SECURITY regardless of which
application is being requested (see workflows/software_access_request.json);
per-application dynamic approver routing is a real feature this project
hasn't built, and shipping an unused column to match an earlier sketch
would just be dead weight.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import RiskLevel, enum_values


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Reuses the `risk_level` Postgres enum type already created in
    # migration 0002 (Employee.risk_level) — see migration 0007's comment
    # for why it's referenced with create_type=False rather than created
    # again.
    risk_level: Mapped[RiskLevel] = mapped_column(
        SAEnum(RiskLevel, name="risk_level", values_callable=enum_values),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
