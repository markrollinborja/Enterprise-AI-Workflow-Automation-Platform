"""Tests for services/integrations/mcp_client.py that aren't already
covered indirectly through executors.py/ai/service.py's own test files.
Phase 13 adds exactly one new thing worth its own coverage here: the
explicit call timeout actually reaches the MCP SDK call, not just the
Settings default it was meant to replace.
"""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import MCPExecutionStatus, MCPToolCaller
from app.repositories import mcp_tool_execution_repo
from app.services.integrations import mcp_client


def test_call_tool_passes_configured_timeout_to_the_transport(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 13: call_tool must thread Settings.mcp_call_timeout_seconds
    through to _call_tool_async (which passes it on to streamablehttp_
    client's own `timeout` kwarg) rather than silently relying on the SDK's
    built-in 30s default — see Settings.mcp_call_timeout_seconds for why
    that distinction matters. Spies on _call_tool_async instead of
    streamablehttp_client itself, matching conftest.py's own mocking
    boundary for every other test in this suite."""
    captured: dict[str, Any] = {}

    async def spy_call_tool_async(
        server_url: str, tool_name: str, arguments: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        captured["timeout_seconds"] = timeout_seconds
        return {"status": "ok"}

    monkeypatch.setattr(
        "app.services.integrations.mcp_client._call_tool_async", spy_call_tool_async
    )

    mcp_client.call_tool(
        db_session,
        tool_name="lookup_employee",
        arguments={"employee_id": "does-not-matter-for-this-test"},
        caller=MCPToolCaller.WORKFLOW_ENGINE,
    )

    assert captured["timeout_seconds"] == get_settings().mcp_call_timeout_seconds


def test_call_tool_records_failure_row_when_the_transport_times_out(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout is just another transport failure from call_tool's own
    perspective — it must still write a FAILED MCPToolExecution row and
    raise MCPToolError, exactly like any other _call_tool_async exception,
    so the engine's existing retry/fail/continue handling picks it up with
    no special-casing (see executors.py)."""

    async def timing_out(
        server_url: str, tool_name: str, arguments: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        raise TimeoutError("simulated MCP call timeout")

    monkeypatch.setattr("app.services.integrations.mcp_client._call_tool_async", timing_out)

    with pytest.raises(mcp_client.MCPToolError):
        mcp_client.call_tool(
            db_session,
            tool_name="lookup_employee",
            arguments={"employee_id": "does-not-matter-for-this-test"},
            caller=MCPToolCaller.WORKFLOW_ENGINE,
        )

    executions = mcp_tool_execution_repo.list_for_timeline(db_session, limit=1)
    assert executions[0].status == MCPExecutionStatus.FAILED
    assert "simulated MCP call timeout" in (executions[0].error_message or "")
