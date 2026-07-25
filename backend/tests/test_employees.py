from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import EmployeeStatus, EmploymentType, RiskLevel, UserRole
from app.models.user import User
from app.repositories import department_repo, employee_repo

TEST_PASSWORD = "CorrectHorse123!"


def _create_user(db: Session, *, email: str, role: UserRole) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Test User",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _auth_headers(client: TestClient, db: Session, role: UserRole, email: str) -> dict[str, str]:
    _create_user(db, email=email, role=role)
    token = _login(client, email)
    return {"Authorization": f"Bearer {token}"}


def test_list_departments_requires_auth(client: TestClient) -> None:
    response = client.get("/departments")
    # HTTPBearer(auto_error=True) returns 403 for a missing header entirely
    # — see the same note in test_auth.py::test_me_requires_token.
    assert response.status_code == 403


def test_create_department_requires_hr_or_admin(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.EMPLOYEE, "plain@cordant.io")
    response = client.post("/departments", json={"name": "Marketing"}, headers=headers)
    assert response.status_code == 403


def test_create_and_list_department(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.HR, "hr-dept@cordant.io")
    create_response = client.post("/departments", json={"name": "Marketing"}, headers=headers)
    assert create_response.status_code == 200
    assert create_response.json()["name"] == "Marketing"

    list_response = client.get("/departments", headers=headers)
    assert list_response.status_code == 200
    assert any(d["name"] == "Marketing" for d in list_response.json())


def test_create_department_conflict(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.HR, "hr-conflict@cordant.io")
    client.post("/departments", json={"name": "Legal"}, headers=headers)
    response = client.post("/departments", json={"name": "Legal"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "ConflictError"


def test_create_employee_requires_hr_or_admin(client: TestClient, db_session: Session) -> None:
    dept = department_repo.create(db_session, name="Engineering")
    headers = _auth_headers(client, db_session, UserRole.EMPLOYEE, "plain2@cordant.io")
    response = client.post(
        "/employees",
        headers=headers,
        json={
            "first_name": "Test",
            "last_name": "Person",
            "work_email": "test.person@cordant.io",
            "job_title": "Engineer",
            "department_id": str(dept.id),
            "employment_type": "full_time",
            "start_date": "2026-01-01",
            "location": "Remote",
        },
    )
    assert response.status_code == 403


def test_create_employee_department_not_found(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.HR, "hr-create1@cordant.io")
    response = client.post(
        "/employees",
        headers=headers,
        json={
            "first_name": "Test",
            "last_name": "Person",
            "work_email": "no-dept@cordant.io",
            "job_title": "Engineer",
            "department_id": "00000000-0000-0000-0000-000000000000",
            "employment_type": "full_time",
            "start_date": "2026-01-01",
            "location": "Remote",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "NotFoundError"


def test_create_employee_and_manager_relationship(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.HR, "hr-create2@cordant.io")
    dept = department_repo.create(db_session, name="Sales")

    manager_response = client.post(
        "/employees",
        headers=headers,
        json={
            "first_name": "Mona",
            "last_name": "Reyes",
            "work_email": "mona.reyes@cordant.io",
            "job_title": "Sales Director",
            "department_id": str(dept.id),
            "employment_type": "full_time",
            "start_date": "2020-01-01",
            "location": "Austin, TX",
        },
    )
    assert manager_response.status_code == 200
    manager_id = manager_response.json()["id"]

    report_response = client.post(
        "/employees",
        headers=headers,
        json={
            "first_name": "Theo",
            "last_name": "Nakamura",
            "work_email": "theo.nakamura@cordant.io",
            "job_title": "Account Executive",
            "department_id": str(dept.id),
            "manager_id": manager_id,
            "employment_type": "full_time",
            "start_date": "2026-02-01",
            "location": "Austin, TX",
        },
    )
    assert report_response.status_code == 200
    body = report_response.json()
    assert body["manager_id"] == manager_id
    assert body["manager_name"] == "Mona Reyes"
    assert body["department_name"] == "Sales"


def test_create_employee_manager_not_found(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.HR, "hr-create4@cordant.io")
    dept = department_repo.create(db_session, name="Support2")
    response = client.post(
        "/employees",
        headers=headers,
        json={
            "first_name": "No",
            "last_name": "Manager",
            "work_email": "no.manager@cordant.io",
            "job_title": "Engineer",
            "department_id": str(dept.id),
            "manager_id": "00000000-0000-0000-0000-000000000000",
            "employment_type": "full_time",
            "start_date": "2026-01-01",
            "location": "Remote",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "NotFoundError"


def test_create_employee_work_email_conflict(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.HR, "hr-create3@cordant.io")
    dept = department_repo.create(db_session, name="Support")
    payload = {
        "first_name": "Dup",
        "last_name": "Licate",
        "work_email": "dup.licate@cordant.io",
        "job_title": "Support Engineer",
        "department_id": str(dept.id),
        "employment_type": "full_time",
        "start_date": "2026-01-01",
        "location": "Remote",
    }
    first = client.post("/employees", headers=headers, json=payload)
    assert first.status_code == 200
    second = client.post("/employees", headers=headers, json=payload)
    assert second.status_code == 409


def test_list_and_get_employee(client: TestClient, db_session: Session) -> None:
    headers = _auth_headers(client, db_session, UserRole.EMPLOYEE, "plain3@cordant.io")
    dept = department_repo.create(db_session, name="Ops")
    employee = employee_repo.create(
        db_session,
        first_name="List",
        last_name="Me",
        work_email="list.me@cordant.io",
        job_title="Ops Analyst",
        department_id=dept.id,
        manager_id=None,
        employment_type=EmploymentType.FULL_TIME,
        start_date=date(2026, 1, 1),
        status=EmployeeStatus.ACTIVE,
        location="Austin, TX",
        risk_level=RiskLevel.LOW,
    )

    list_response = client.get("/employees", headers=headers)
    assert list_response.status_code == 200
    assert any(e["work_email"] == "list.me@cordant.io" for e in list_response.json())

    get_response = client.get(f"/employees/{employee.id}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["first_name"] == "List"
