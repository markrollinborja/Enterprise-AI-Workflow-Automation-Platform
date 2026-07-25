from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.repositories import department_repo
from app.schemas.department import DepartmentCreate, DepartmentResponse


def list_departments(db: Session) -> list[DepartmentResponse]:
    return [DepartmentResponse.model_validate(d) for d in department_repo.list_all(db)]


def create_department(db: Session, payload: DepartmentCreate) -> DepartmentResponse:
    if department_repo.get_by_name(db, payload.name) is not None:
        raise ConflictError("A department with this name already exists")
    department = department_repo.create(db, name=payload.name)
    return DepartmentResponse.model_validate(department)
