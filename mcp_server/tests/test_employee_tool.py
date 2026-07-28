"""lookup_employee has no mock mode (see app/tools/employee.py) — these
tests hit a real, migrated Postgres database (see conftest.py's docstring
for the one-time setup this file needs: `docker compose up -d db`, then
`alembic upgrade head` from backend/). Each test that needs a row inserts
its own department/employee via a plain psycopg connection and cleans up
afterward — no dependency on backend's seed data.
"""

from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest

from app.db import get_connection
from app.schemas import LookupEmployeeInput
from app.tools.employee import execute_lookup_employee


@pytest.fixture
def seeded_employee() -> Iterator[UUID]:
    department_id = uuid4()
    employee_id = uuid4()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO departments (id, name) VALUES (%(id)s, %(name)s)",
            {"id": str(department_id), "name": f"Test Dept {uuid4()}"},
        )
        cur.execute(
            """
            INSERT INTO employees (
                id, first_name, last_name, work_email, job_title,
                department_id, employment_type, start_date, status,
                location, risk_level
            ) VALUES (
                %(id)s, %(first_name)s, %(last_name)s, %(work_email)s,
                %(job_title)s, %(department_id)s, %(employment_type)s,
                %(start_date)s, %(status)s, %(location)s, %(risk_level)s
            )
            """,
            {
                "id": str(employee_id),
                "first_name": "Jamie",
                "last_name": "Rivera",
                "work_email": f"jamie-{uuid4()}@cordant.io",
                "job_title": "Software Engineer",
                "department_id": str(department_id),
                "employment_type": "full_time",
                "start_date": date(2026, 1, 1),
                "status": "active",
                "location": "Austin, TX",
                "risk_level": "low",
            },
        )
        conn.commit()

    yield employee_id

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM employees WHERE id = %(id)s", {"id": str(employee_id)})
        cur.execute("DELETE FROM departments WHERE id = %(id)s", {"id": str(department_id)})
        conn.commit()


def test_found_employee_returns_directory_fields(seeded_employee: UUID) -> None:
    result = execute_lookup_employee(LookupEmployeeInput(employee_id=str(seeded_employee)))

    assert result.found is True
    assert result.employee_id == str(seeded_employee)
    assert result.first_name == "Jamie"
    assert result.last_name == "Rivera"
    assert result.job_title == "Software Engineer"
    assert result.department_name is not None and result.department_name.startswith("Test Dept")
    assert result.employment_type == "full_time"
    assert result.status == "active"
    assert result.risk_level == "low"


def test_unknown_employee_id_returns_found_false_not_an_error() -> None:
    result = execute_lookup_employee(LookupEmployeeInput(employee_id=str(uuid4())))

    assert result.found is False
    assert result.first_name is None


def test_malformed_employee_id_returns_found_false_not_an_error() -> None:
    result = execute_lookup_employee(LookupEmployeeInput(employee_id="not-a-uuid"))

    assert result.found is False
