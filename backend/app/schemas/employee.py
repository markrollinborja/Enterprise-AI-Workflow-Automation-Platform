from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.models.enums import EmployeeStatus, EmploymentType, RiskLevel


class EmployeeCreate(BaseModel):
    first_name: str
    last_name: str
    work_email: EmailStr
    personal_email: EmailStr | None = None
    job_title: str
    department_id: UUID
    manager_id: UUID | None = None
    employment_type: EmploymentType
    start_date: date
    location: str
    risk_level: RiskLevel = RiskLevel.LOW
    status: EmployeeStatus = EmployeeStatus.ACTIVE


class EmployeeUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    department_id: UUID | None = None
    manager_id: UUID | None = None
    employment_type: EmploymentType | None = None
    status: EmployeeStatus | None = None
    location: str | None = None
    risk_level: RiskLevel | None = None


class EmployeeResponse(BaseModel):
    """Not a straight from_attributes pass-through — department_name and
    manager_name are derived by the service layer from eager-loaded
    relationships (see services/employees/service.py), so the frontend gets
    readable names instead of having to resolve UUIDs itself."""

    id: UUID
    first_name: str
    last_name: str
    work_email: EmailStr
    job_title: str
    department_id: UUID
    department_name: str | None
    manager_id: UUID | None
    manager_name: str | None
    employment_type: EmploymentType
    start_date: date
    status: EmployeeStatus
    location: str
    risk_level: RiskLevel
    created_at: datetime
    updated_at: datetime
