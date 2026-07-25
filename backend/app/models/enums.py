import enum


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Pass as `values_callable` to every SQLAlchemy Enum column, always.

    SQLAlchemy's default behavior for a Python str Enum is to persist the
    member's *name* ("HR") instead of its *value* ("hr") — but every Postgres
    enum type in this project's migrations is defined using the lowercase
    values. Skipping this on Phase 3's User.role column caused every insert
    to fail with "invalid input value for enum" until it was found and
    fixed; this helper exists so that bug can't happen again on a new column.
    """
    return [e.value for e in enum_cls]


class UserRole(str, enum.Enum):
    """The six V1 roles — see docs/architecture/authentication.md and
    docs/decisions/ for why these six and not more (no Finance, no CEO/
    Stakeholder role — neither onboarding nor access-request workflows need
    them)."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"
    IT = "it"
    SECURITY = "security"
    ADMINISTRATOR = "administrator"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACTOR = "contractor"


class EmployeeStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"  # reserved for Phase 6+ onboarding-in-progress state
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class RiskLevel(str, enum.Enum):
    """Directory-level risk classification. Manually set for now (HR
    judgment call); Phase 8's rules engine will read this field when routing
    approvals, but nothing computes it automatically yet."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
