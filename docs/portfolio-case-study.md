# Meridian Flow: Enterprise Employee Workflow Automation Platform

**A reusable workflow orchestration platform for internal employee operations, built to prove I can design a system that automates more than one business process, not just script a single one.**

GitHub: https://github.com/markrollinborja/enterprise-ai-workflow-automation-platform

## The problem

My first automation project, the AI IT Ticket Automation Platform, proves I can automate one specific workflow end to end: a Jira ticket comes in, gets classified and routed, and Slack gets notified. That's a real, useful pattern, but on its own it doesn't prove something hiring managers for automation and platform roles actually care about: can the same engine support more than one business process without being rebuilt for each one.

Meridian Flow answers that directly. It's an internal employee operations platform that automates two different HR and IT processes, employee onboarding and software access requests, on top of one shared workflow engine, approval system, rules engine, notification layer, and audit trail. The second workflow reuses the first workflow's infrastructure almost entirely. That reuse is the actual point of the project.

## What I built

The platform runs two configurable, JSON-defined workflows:

- **Employee onboarding**: HR creates an employee record, which triggers a workflow that routes for manager approval, calls an AI service to recommend an access package (constrained to the actual approved catalog, not a free-text suggestion), routes to IT for review, creates real Jira onboarding tasks, schedules a real Google Calendar orientation event, sends a real Slack notification, and completes with a full audit trail.
- **Software access request**: any employee can request access to an internal application. A deterministic rules engine classifies risk (based on the employee's own risk profile and the application's sensitivity) and decides whether the request auto-approves, needs manager approval, or needs a full manager plus IT plus security chain. High-risk requests get an AI-generated summary of the employee's justification to speed up human review, but the AI never approves anything itself.

Both workflows run on the same `WorkflowInstance` / `WorkflowStepInstance` state machine, the same approval engine, the same MCP-backed integration layer, and the same audit log. Building the second workflow took a fraction of the effort of the first, which is the evidence that the architecture is actually reusable rather than just described as reusable.

**Stack**: Python 3.12, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Docker Compose, React, TypeScript, Vite, Tailwind CSS, a real MCP server (FastMCP) exposing typed tools to an agentic AI service, OpenAI's API for structured, schema-constrained outputs, and real integrations with Jira Cloud, Slack, and Google Calendar.

## Why MCP, specifically

The platform has two different callers that both need to trigger the same external actions (create a Jira ticket, send a Slack message, look up an employee): the workflow engine, deterministically, and the AI service, agentically, when it decides mid-reasoning that it needs more context. Rather than wiring those up as two separate integration paths, both go through one MCP server exposing four typed, validated, audited tools (`create_jira_task`, `send_slack_notification`, `schedule_calendar_event`, `lookup_employee`). The AI service's access-recommendation step actually runs a real tool-calling loop: the model can call `lookup_employee` itself before answering, instead of receiving employee data pre-stuffed into its prompt. Every tool call, from either caller, writes one audit row, success or failure. That's the concrete difference between "an LLM that could theoretically call any API" and "an LLM that can call exactly four named, permissioned, logged actions and nothing else."

## Two decisions I'd point to in an interview

**A race condition I introduced, then found in testing before it shipped.** The workflow engine needs to advance an instance from two different places, an inline call right after an approval decision, and a background worker polling for retries, without letting them collide on the same instance. My first fix used a Postgres advisory lock acquired and released on the same SQLAlchemy session used for the rest of the work. That's wrong: Postgres ties an advisory lock to the physical connection that issued it, and a default SQLAlchemy session returns its connection to the pool on every commit, of which the workflow engine does several per call. The lock could end up held by an idle, already-returned connection, orphaned forever, with the next attempt to advance that same instance hanging indefinitely. The test suite caught it hanging on exactly that sequence, not a design review. The fix was to acquire and hold the lock on a dedicated connection for the whole call, independent of however many times the session itself commits. Full writeup in the repo's ADR-0013.

**Running the platform against real external systems, not just mocks, before calling any integration done.** Mock mode proves the contract, that a tool call returns the right shape and the engine reacts to failure correctly. It structurally cannot prove the integration actually works. Running both workflows end to end against live Jira, Slack, and Google Calendar surfaced four real failure modes mocks never could have caught: a Jira error handler that discarded the response body where the actual rejection reason lived; a Google Calendar service account that can never invite attendees without paid Workspace delegation, which is a permanent constraint, not a retry problem; a Slack notification scheme that assumed real per-user identities the fictional demo employees don't have; and a role-pool approval step that, by original design, sent zero notifications to anyone, which reads as a broken workflow in a live demo even though the underlying state was correct. Each got its own fix and its own documented reasoning rather than a silent patch. Full incident-by-incident writeup in the repo's troubleshooting doc.

## Reliability and testing

Every important workflow action writes an audit event: trigger received, rule evaluated, AI called, approval requested and decided, integration called and its result, retry attempted, workflow completed or failed. Failed steps are retried automatically with backoff up to a configured limit, and an administrator can manually retry a step after fixing whatever caused it to fail, with the retry distinguished from an automatic one in the audit trail. CI runs three jobs on every push (backend, MCP server, frontend), each with linting, type checking, and a pytest suite covering the state machine, the rules engine's full risk matrix, the approval engine's authorization rules, the AI service's graceful-fallback behavior when no API key is configured, and the advisory-lock fix described above, all against mocked external clients so the suite never depends on live credentials.

## Where it stands and what's next

Version 1 is feature-complete for both workflows and running locally against real Jira, Slack, and Google Calendar credentials. It hasn't been deployed to a hosted environment yet, and a few things are deliberately out of scope for V1: a visual workflow builder, SLA timers and escalation, delegated approvals, and true multi-person role-pool assignment (the current fan-out-to-everyone-with-a-role approach is fine at this project's scale but wouldn't hold up for a real multi-person IT team, and that's documented as a known limitation rather than solved).

## What this project demonstrates

Workflow orchestration and business process automation, human-in-the-loop approval design with real authorization rules, a deterministic rules engine kept separate from AI so the AI is only used where it adds real interpretive value, a real MCP server as the tool boundary for both a scripted engine and an agentic AI caller, and the engineering habit of finding and fixing my own concurrency bugs and integration gaps through actual testing, real-mode runs, and honest documentation of what broke and why, rather than a project that only ever ran against mocks.
