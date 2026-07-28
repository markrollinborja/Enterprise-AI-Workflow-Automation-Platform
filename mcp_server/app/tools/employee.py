"""lookup_employee — the one read-only MCP tool in this server, and the
only one an AI agent (not the workflow engine) actually calls: backend's
services/ai/service.py gives an OpenAI model this tool's schema and asks
it to look up an employee's job title/department for itself before
recommending an access package, rather than the backend pre-fetching that
context and stuffing it into the prompt. This is what makes MCP a real
architectural component here (see docs/architecture/mcp-architecture.md,
"How the AI agent discovers and invokes tools") rather than a tool the
backend could just as easily have called directly.

No mock mode, unlike jira.py/slack.py/calendar.py — those simulate an
external SaaS a demo shouldn't depend on being live; this tool reads
Meridian Flow's own database, which the platform already requires to run
at all. There's nothing to mock.

execute_lookup_employee is the plain, directly-testable function —
server.py wraps it with @mcp.tool(), same pattern as every other tool
here. Split further into _query_employee_row (the one DB-touching line)
so the shaping/validation logic above it is easy to reason about
separately from the SQL.
"""

import uuid
from typing import Any

from app.db import get_connection
from app.schemas import LookupEmployeeInput, LookupEmployeeOutput

_QUERY = """
    SELECT
        e.id, e.first_name, e.last_name, e.work_email, e.job_title,
        e.employment_type, e.status, e.risk_level, d.name AS department_name
    FROM employees e
    JOIN departments d ON d.id = e.department_id
    WHERE e.id = %(employee_id)s
"""


def execute_lookup_employee(input_data: LookupEmployeeInput) -> LookupEmployeeOutput:
    try:
        employee_uuid = uuid.UUID(input_data.employee_id)
    except ValueError:
        # A malformed ID is the model's mistake, not a system failure —
        # found=False lets it react (e.g. try again, or give up
        # gracefully) the same way it would for a genuinely unknown ID.
        return LookupEmployeeOutput(found=False)

    row = _query_employee_row(employee_uuid)
    if row is None:
        return LookupEmployeeOutput(found=False)

    return LookupEmployeeOutput(
        found=True,
        employee_id=str(row["id"]),
        first_name=row["first_name"],
        last_name=row["last_name"],
        work_email=row["work_email"],
        job_title=row["job_title"],
        department_name=row["department_name"],
        employment_type=row["employment_type"],
        status=row["status"],
        risk_level=row["risk_level"],
    )


def _query_employee_row(employee_id: uuid.UUID) -> dict[str, Any] | None:
    """The only DB-touching line in this tool. A connection failure raises
    here and is left to propagate — a real infrastructure problem, not a
    "not found" business outcome, so it should surface as a genuine MCP
    tool error (FastMCP turns an uncaught exception into result.isError),
    not be swallowed into found=False."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_QUERY, {"employee_id": str(employee_id)})
        result = cur.fetchone()
        return dict(result) if result is not None else None
