"""No fixtures needed yet: app.core.config.Settings defaults mcp_mock_mode
to True, which every tool's execute_* function checks first — so simply not
setting real-mode env vars in the test environment is enough to guarantee
every test here exercises the mock path, no real network calls, no real
credentials needed. get_settings() is @lru_cache'd; tests don't override
settings, so that cache never needs clearing between tests here.

Exception: test_employee_tool.py. lookup_employee has no mock mode (see
its docstring) — it always reads real rows, so those tests need an actual,
migrated Postgres reachable at Settings.database_url (the default already
matches docker-compose.yml's host-mapped port: run `docker compose up -d
db` from the repo root, then `alembic upgrade head` from backend/, before
running this suite). Every other test file here has no such dependency.
"""
