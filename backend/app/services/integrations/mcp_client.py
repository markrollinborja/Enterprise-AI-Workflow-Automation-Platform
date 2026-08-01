"""The single place backend/ knows how to reach the real MCP server
(mcp_server/, its own process — see ADR-0005, ADR-0012). Every Jira/Slack/
Calendar/employee-lookup call, from either caller (the workflow engine's
executors.py, or the AI service's agentic tool-calling loop), goes through
`call_tool` here — nothing else in backend/ imports the `mcp` client SDK
directly.

Two deliberate design choices, both explained in full in ADR-0012:

1. Sync-wrapped, connect-per-call. The `mcp` SDK's client is async
   (anyio-based); this codebase is sync top to bottom. `call_tool` opens a
   fresh connection and session for every single call via `anyio.run(...)`
   rather than maintaining a persistent client session — the right
   tradeoff at this project's call volume (a handful of tool calls per
   workflow instance, not a hot path), and it only works because `call_tool`
   is always invoked from a plain sync thread with no event loop already
   running (never from inside an async FastAPI route body directly).

2. No internal retry. The workflow engine's step-level retry (Phase 6:
   `scheduled_at` + the worker polling `waiting_external`) is the actual
   retry mechanism for a failed mcp_tool step — this function calls a tool
   exactly once and reports success or failure. Retrying here too would
   multiply attempts (engine retries x internal retries) instead of
   bounding them at the step's own `max_attempts`.

Every call, success or failure, writes one MCPToolExecution row — this is
the audit trail Principle 4 asks for ("integration called" / "integration
succeeded" / "integration failed" as their own inspectable rows).

Note on the `streamablehttp_client` import below: pinned to mcp==1.9.4
(see requirements.txt), which exports that name with no underscore between
"streamable" and "http". Later SDK releases rename it to
`streamable_http_client` — confirmed the hard way, not from the docs site,
which already described the newer name at write-time. If this pin is ever
bumped, re-check this import against whatever's actually installed rather
than trusting the current docs site or this comment.
"""

import json
import time
import uuid
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import MCPExecutionStatus, MCPToolCaller
from app.repositories import mcp_tool_execution_repo


class MCPToolError(Exception):
    """Raised on any tool-call failure — MCP transport error, the tool
    rejecting its input, or (real mode) the underlying external API
    erroring. Callers (executors.py, services/ai/service.py) catch this the
    same way services/ai/service.py already catches OpenAI failures: turn
    it into their own graceful StepExecutionResult/AIActionResult, never
    let it propagate as an unhandled exception into the engine."""


def _describe_exception(exc: BaseException) -> str:
    """`anyio.run` executes `_call_tool_async` inside its own TaskGroup, so
    a failure anywhere in the streamablehttp_client/ClientSession teardown
    (a dropped connection, a timeout while a real external API call like
    Slack's is still in flight, ...) surfaces here as `ExceptionGroup:
    unhandled errors in a TaskGroup (1 sub-exception)` — technically
    accurate, useless for debugging: it names the wrapper, not what
    actually broke. Unwraps down to the real underlying exception so
    MCPToolExecution.error_message (and whatever a human reads off the
    Workflow Detail page) says what actually happened."""
    current = exc
    while isinstance(current, (ExceptionGroup, BaseExceptionGroup)) and current.exceptions:
        current = current.exceptions[0]
    return f"{type(current).__name__}: {current}"


def call_tool(
    db: Session,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    caller: MCPToolCaller,
    workflow_instance_id: uuid.UUID | None = None,
    step_instance_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Calls `tool_name` once against the MCP server with `arguments`
    (flat kwargs matching the tool's own schema — see mcp_server/app/server.py),
    writes one MCPToolExecution row, and returns the tool's structured
    result dict on success. Raises MCPToolError on any failure; never
    returns a partial or unvalidated result."""
    settings = get_settings()
    started = time.monotonic()
    try:
        result = anyio.run(
            _call_tool_async,
            settings.mcp_server_url,
            tool_name,
            arguments,
            settings.mcp_call_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — every failure here must be
        # logged and re-raised as MCPToolError, not swallowed or left as a
        # raw, uncategorized exception the caller wasn't written to expect.
        duration_ms = int((time.monotonic() - started) * 1000)
        description = _describe_exception(exc)
        mcp_tool_execution_repo.create(
            db,
            tool_name=tool_name,
            caller=caller,
            workflow_instance_id=workflow_instance_id,
            step_instance_id=step_instance_id,
            input_params=arguments,
            output_result=None,
            status=MCPExecutionStatus.FAILED,
            mock_mode=settings.mcp_mock_mode,
            duration_ms=duration_ms,
            error_message=description,
        )
        raise MCPToolError(description) from exc

    duration_ms = int((time.monotonic() - started) * 1000)
    mcp_tool_execution_repo.create(
        db,
        tool_name=tool_name,
        caller=caller,
        workflow_instance_id=workflow_instance_id,
        step_instance_id=step_instance_id,
        input_params=arguments,
        output_result=result,
        status=MCPExecutionStatus.COMPLETED,
        mock_mode=settings.mcp_mock_mode,
        duration_ms=duration_ms,
        error_message=None,
    )
    return result


async def _call_tool_async(
    server_url: str, tool_name: str, arguments: dict[str, Any], timeout_seconds: float
) -> dict[str, Any]:
    # `timeout` bounds regular request/response round trips (session init,
    # the tool call itself); `sse_read_timeout` bounds how long the
    # underlying stream will wait for a new server-sent event before
    # disconnecting — left at the SDK's own 5-minute default since it's not
    # what a hung tool call would actually block on here. See
    # Settings.mcp_call_timeout_seconds for why 10s.
    async with streamablehttp_client(server_url, timeout=timeout_seconds) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                error_text = "; ".join(
                    block.text for block in result.content if hasattr(block, "text")
                )
                raise RuntimeError(error_text or f"tool '{tool_name}' reported an error")
            # Prefer structuredContent when the installed SDK build exposes
            # it (added to the MCP spec 2025-06-18; confirmed via mypy
            # against the actually-installed mcp==1.9.4 that
            # CallToolResult doesn't carry it at this pin — one more
            # version-drift surprise, same class as the streamablehttp_client
            # rename). getattr, not a direct attribute access, so this
            # doesn't hard-fail on a version that lacks the field. Falls
            # back to parsing the JSON text block FastMCP populates
            # regardless of SDK version — every one of this project's
            # tools returns a Pydantic model, which FastMCP always
            # JSON-serializes into a TextContent block whether or not
            # structuredContent is also present.
            structured = getattr(result, "structuredContent", None)
            if structured is not None:
                return dict(structured)
            for block in result.content:
                text = getattr(block, "text", None)
                if text is None:
                    continue
                try:
                    return dict(json.loads(text))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise RuntimeError(
                        f"tool '{tool_name}' returned non-JSON text content"
                    ) from exc
            raise RuntimeError(f"tool '{tool_name}' returned no usable content")
