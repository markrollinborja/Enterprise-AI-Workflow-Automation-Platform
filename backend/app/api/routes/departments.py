from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.department import DepartmentCreate, DepartmentResponse
from app.services.departments import service as department_service

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=list[DepartmentResponse])
def list_departments(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[DepartmentResponse]:
    return department_service.list_departments(db)


@router.post("", response_model=DepartmentResponse)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.HR, UserRole.ADMINISTRATOR)),
) -> DepartmentResponse:
    return department_service.create_department(db, payload)
