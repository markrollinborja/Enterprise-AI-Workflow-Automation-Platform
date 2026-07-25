import enum


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
