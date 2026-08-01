from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.employee import Employee
from app.models.user import User
from app.repositories import department_repo, employee_repo
from app.schemas.employee import EmployeeCreate, EmployeeResponse, EmployeeUpdate
from app.services.workflows.service import start_workflow


def _to_response(employee: Employee) -> EmployeeResponse:
    """Builds the readable department_name/manager_name fields from the
    eager-loaded relationships — see the note on EmployeeResponse."""
    return EmployeeResponse(
        id=employee.id,
        first_name=employee.first_name,
        last_name=employee.last_name,
        work_email=employee.work_email,
        job_title=employee.job_title,
        department_id=employee.department_id,
        department_name=employee.department.name if employee.department else None,
        manager_id=employee.manager_id,
        manager_name=(
            f"{employee.manager.first_name} {employee.manager.last_name}"
            if employee.manager
            else None
        ),
        employment_type=employee.employment_type,
        start_date=employee.start_date,
        status=employee.status,
        location=employee.location,
        risk_level=employee.risk_level,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


def list_employees(db: Session) -> list[EmployeeResponse]:
    return [_to_response(e) for e in employee_repo.list_all(db)]


def get_employee(db: Session, employee_id: UUID) -> EmployeeResponse:
    employee = employee_repo.get_by_id(db, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found")
    return _to_response(employee)


def create_employee(
    db: Session, payload: EmployeeCreate, *, current_user: User
) -> EmployeeResponse:
    if department_repo.get_by_id(db, payload.department_id) is None:
        raise NotFoundError("Department not found")
    if payload.manager_id is not None and employee_repo.get_by_id(db, payload.manager_id) is None:
        raise NotFoundError("Manager not found")
    if employee_repo.get_by_work_email(db, payload.work_email) is not None:
        raise ConflictError("An employee with this work email already exists")

    created = employee_repo.create(db, **payload.model_dump())

    # This is the real "employee.created" trigger for the onboarding
    # workflow (workflows/employee_onboarding.json). Before this, the only
    # place that ever called start_workflow for onboarding was the seed
    # script's one-off demo instance for Jordan Lee — creating an employee
    # through the real API silently did nothing beyond the INSERT. dedup_key
    # is keyed on the employee id (one employee should only ever get one
    # onboarding instance), not a random uuid like access-requests uses,
    # matching seed.py's own dedup_key convention for this workflow.
    start_workflow(
        db,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(created.id)},
        dedup_key=f"employee_onboarding:{created.id}",
        initiated_by_user_id=current_user.id,
        employee_id=created.id,
    )

    # Re-fetch with relationships eager-loaded — db.refresh() after insert
    # only refreshes columns, not relationships.
    return _to_response(employee_repo.get_by_id(db, created.id))  # type: ignore[arg-type]


def update_employee(db: Session, employee_id: UUID, payload: EmployeeUpdate) -> EmployeeResponse:
    employee = employee_repo.get_by_id(db, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found")
    if (
        payload.department_id is not None
        and department_repo.get_by_id(db, payload.department_id) is None
    ):
        raise NotFoundError("Department not found")
    if payload.manager_id is not None and employee_repo.get_by_id(db, payload.manager_id) is None:
        raise NotFoundError("Manager not found")

    updated = employee_repo.update(db, employee, **payload.model_dump(exclude_unset=True))
    return _to_response(employee_repo.get_by_id(db, updated.id))  # type: ignore[arg-type]
