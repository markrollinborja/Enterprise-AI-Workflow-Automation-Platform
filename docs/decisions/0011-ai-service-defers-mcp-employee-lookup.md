# ADR-0011: AI Service Calls employee_repo Directly, Not MCP, Until Phase 10

**Status:** Accepted — 2026-07-27

**Context:** The original Phase 1 sketch of `service-boundaries.md`'s "ai" section described `services/ai` as an MCP *client*, calling a read-only `lookup_employee` tool to gather context before generating an onboarding access recommendation. That sketch predates Phase 9 actually being built — no MCP server exists yet; it's Phase 10's deliverable.

**Decision:** Phase 9's `services/ai/service.py` calls `employee_repo.get_by_id` directly for the one piece of context `recommend_access_package` needs (job title, department, employment type). No MCP server, no MCP client, stood up early.

**Alternatives considered:**

- **Stand up a minimal real MCP server now**, a phase early, with just the one read-only `lookup_employee` tool, to keep the AI service's dependency exactly as originally sketched. Rejected: Phase 10's entire point is "build the real MCP server, cross a real protocol boundary" (ADR-0005) — building a (necessarily incomplete, one-tool) version of it a phase early to satisfy one internal read doesn't demonstrate anything Phase 10 won't demonstrate more completely, and adds a real process/deployment/testing surface for a feature (an internal DB read) that doesn't need one yet.
- **Leave the doc as originally written and build against it anyway.** Rejected as dishonest — the doc would describe an architecture the code doesn't have, which is worse than revising the doc to match a decision actually made with reasons attached.

**Consequences:** `services/ai` currently has a real, direct dependency on `repositories/employee_repo` that `service-boundaries.md`'s "ai" section no longer describes as MCP-mediated. When Phase 10 builds the real MCP server for Jira/Slack/Calendar, adding `lookup_employee` as a fourth tool and swapping this one call over is a one-line change in `services/ai/service.py` (call the MCP client instead of the repo directly), not a redesign — the AI service's *use* of the employee data (what it does with job title/department once it has them) doesn't change at all. This is the same judgment call as ADR-0009's `Application.owner_role` cut: don't build the more "correct"-looking version of something a phase early when nothing yet depends on it being that way.
