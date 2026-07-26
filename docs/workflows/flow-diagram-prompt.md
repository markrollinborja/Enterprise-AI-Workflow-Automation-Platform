# Prompt: Complete Process Flow Diagram (Meridian Flow)

Use this prompt in a diagramming tool (Whimsical AI, Eraser DiagramGPT, Miro AI, Lucidchart AI, or another Claude/LLM session) to generate a userflow/swimlane diagram covering both V1 workflows end to end. This is the source material for the "Onboarding workflow diagram" and "Access request decision tree" portfolio deliverables.

---

Create a swimlane user-flow diagram for **Meridian Flow**, an enterprise employee workflow automation platform. Show the complete process across both of its core workflows, with one horizontal swimlane per actor: **HR**, **Employee**, **Manager**, **IT**, **Security**, **AI Agent (stub)**, **MCP Integrations**, and **System / Workflow Engine**.

## Workflow 1 — Employee Onboarding
*(triggered automatically when HR creates a new employee record)*

1. HR submits a new employee record (Employee Directory)
2. System validates required employee fields — if invalid, workflow **fails** immediately
3. System requests Manager approval; workflow **pauses**
4. Manager approves or rejects
   - Rejected → HR notified, workflow ends (**rejected**)
   - Approved → continue
5. AI Agent reviews job title/department and recommends an access package (defaults to flagging for human review)
6. If flagged for review → IT reviews and approves/rejects the recommended access package; workflow **pauses** again
   - Rejected → workflow ends (**rejected**)
   - If not flagged → this step is skipped entirely
7. System (via MCP) creates Jira onboarding tasks — retries up to 3x with backoff on failure
8. System (via MCP) schedules orientation on Google Calendar — retries up to 3x with backoff on failure
9. System (via MCP) sends a Slack notification — failure here does **not** stop the workflow
10. Workflow **completes**; every step recorded in the audit trail

## Workflow 2 — Software Access Request
*(triggered manually by an employee)*

1. Employee submits an access request (application + justification)
2. System validates the request — if invalid, workflow **fails** immediately
3. System requests Manager approval; workflow **pauses**
   - Rejected → workflow ends (**rejected**)
4. If the requested application's risk level is medium or high → AI Agent summarizes the justification
5. If risk level is medium or high → IT/application-owner approval required; workflow **pauses**
   - Rejected → workflow ends (**rejected**)
6. If risk level is high → Security approval also required; workflow **pauses**
   - Rejected → workflow ends (**rejected**)
7. System (via MCP) creates an IT fulfillment task in Jira — retries on failure
8. System (via MCP) notifies the employee via Slack of the outcome
9. Workflow **completes**; every step recorded in the audit trail

## Cross-cutting behavior to depict

- Every step logs to an audit trail (show as a small annotation or side note, not a full lane)
- Any step can retry with backoff, permanently fail the workflow, or fail-but-continue, depending on its configured failure behavior
- Approvals are the *only* points where the flow pauses for a human
- A rejection at any approval step ends the workflow immediately — nothing downstream ever runs
- The access-request approval chain literally grows with risk: manager only (low) → +IT (medium) → +IT+Security (high)

## Style

Horizontal swimlane flowchart, one lane per actor. Diamond shapes for decision/approval points. Distinct, visually different end-state shapes for **Completed** / **Rejected** / **Failed**. Clean and professional — this needs to work as a GitHub README image and as something walked through live in an interview.
