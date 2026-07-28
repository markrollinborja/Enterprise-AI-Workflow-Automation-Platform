"""Minimal, ORM-independent database access for mcp_server.

mcp_server and backend are two genuinely separate processes that happen to
share one Postgres schema (ADR-0005) — this module does not import
backend's SQLAlchemy models, and mcp_server never runs migrations (backend/
alembic is the only schema owner; see Settings.database_url's docstring).

lookup_employee (app/tools/employee.py) is the only tool that touches the
database, it only ever reads, and it's called rarely (a handful of times
per onboarding workflow, from the AI service's tool-calling loop) — a
plain connect-per-call helper is the right amount of machinery. No
connection pool, matching the same tradeoff backend's own
services/integrations/mcp_client.py makes for its MCP calls (see
ADR-0012): pooling is real complexity that only pays for itself at a call
volume this project doesn't have.
"""

import psycopg
from psycopg.rows import DictRow, dict_row

from app.core.config import get_settings


def get_connection() -> psycopg.Connection[DictRow]:
    """One new connection per call. Row factory returns dict-like rows
    (column name -> value) so callers never need to know column order —
    see app/tools/employee.py."""
    settings = get_settings()
    return psycopg.connect(settings.database_url, row_factory=dict_row)
