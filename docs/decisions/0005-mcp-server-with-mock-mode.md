# ADR-0005: Real MCP Server as a Separate Process, Mock Mode by Default

**Status:** Accepted — 2026-07-23

**Context:** MCP is the project's primary differentiator and highest hiring-value feature. It could be implemented as an in-process module the backend calls as plain functions ("MCP-shaped" code) or as an actual MCP server the backend and AI service connect to over the protocol.

**Decision:** `mcp_server/` runs as its own process (own Docker Compose service, HTTP/SSE transport). All four tools (`create_jira_task`, `send_slack_notification`, `schedule_calendar_event`, `lookup_employee`) default to `MOCK_MODE=true`.

**Alternatives considered:** In-process "tool" functions called directly — rejected: doesn't cross an actual protocol boundary, so "I built and used an MCP server" wouldn't be a fully true claim. Defaulting to real external API calls — rejected: makes every demo/interview dependent on three external services staying reachable and credentials staying valid at that exact moment; unacceptable reliability risk for something meant to be shown live.

**Consequences:** Slightly more setup (a real server process, a real client connection) than an in-process shortcut — worth it, since it's the whole point of the project. Mock mode means the demo never fails because of an external outage, at the cost of the live demo not literally touching real Jira/Slack/Calendar unless deliberately switched to real mode for that purpose.

**See also:** [mcp-architecture.md](../architecture/mcp-architecture.md)
