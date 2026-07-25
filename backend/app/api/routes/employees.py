from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.employee import EmployeeCreate, EmployeeResponse, EmployeeUpdate
from app.services.employees import service as employee_service

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeResponse])
def list_employees(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[EmployeeResponse]:
    """Visible to any authenticated user, like most company org directories
    — restricting create/update to HR and Administrator is where the real
    access control lives, not on reading the roster."""
    return employee_service.list_employees(db)


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: UUID,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> EmployeeResponse:
    return employee_service.get_employee(db, employee_id)


@router.post("", response_model=EmployeeResponse)
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.HR, UserRole.ADMINISTRATOR)),
) -> EmployeeResponse:
    return employee_service.create_employee(db, payload)


@router.patch("/{employee_id}", response_model=EmployeeResponse)
def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.HR, UserRole.ADMINISTRATOR)),
) -> EmployeeResponse:
    return employee_service.update_employee(db, employee_id, payload)
