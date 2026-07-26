# Workflow Flow Diagrams

Generated directly from `workflows/employee_onboarding.json`, `workflows/software_access_request.json`, and the execution engine (`backend/app/services/workflows/service.py`) — not from a prose description, so these are guaranteed to match what the code actually does. Supersedes any diagram generated from `flow-diagram-prompt.md` alone; verify against these if the two ever disagree.

Box text is plain English for readability — see the "Step key reference" table under each diagram to map a box back to its `step_key` in the JSON definition.

## Workflow 1 — Employee Onboarding

```mermaid
flowchart TD
    Start(["HR creates a new employee record"]) --> Validate{"Are all required\nfields present?"}
    Validate -- No --> Failed1[["Failed"]]
    Validate -- Yes --> MgrApproval[/"Manager reviews and\napproves the onboarding"/]

    MgrApproval -- Rejected --> Rejected1(("Rejected"))
    MgrApproval -- Approved --> AI["AI recommends an access package"]

    AI --> ReviewCheck{"Does the recommendation\nneed human review?"}
    ReviewCheck -- Yes --> ITApproval[/"IT reviews the\nrecommended access package"/]
    ReviewCheck -- "No — skipped" --> Jira

    ITApproval -- Rejected --> Rejected1
    ITApproval -- Approved --> Jira

    Jira{{"Create onboarding\ntasks in Jira"}}
    Jira -- "Fails, under 3 attempts" --> JiraWait["Wait, then retry\n(with backoff)"] --> Jira
    Jira -- "Fails, 3 attempts used up" --> Failed1
    Jira -- Succeeds --> Cal

    Cal{{"Schedule orientation\nin Google Calendar"}}
    Cal -- "Fails, under 3 attempts" --> CalWait["Wait, then retry\n(with backoff)"] --> Cal
    Cal -- "Fails, 3 attempts used up" --> Failed1
    Cal -- Succeeds --> Slack

    Slack{{"Send Slack notification"}}
    Slack -- Fails --> Continue1["Notification failed —\nworkflow continues anyway"]
    Slack -- Succeeds --> Complete1(["Completed"])
    Continue1 --> Complete1
```

**Step key reference:** Validate = `validate_employee` · Manager review = `manager_approval` · AI recommendation = `recommend_access` · IT review = `it_review_access` · Jira = `create_it_tasks` · Calendar = `schedule_orientation` · Slack = `notify_slack`

## Workflow 2 — Software Access Request

```mermaid
flowchart TD
    Start2(["Employee submits an access request"]) --> Validate2{"Are all required\nfields present?"}
    Validate2 -- No --> Failed2[["Failed"]]
    Validate2 -- Yes --> MgrApproval2[/"Manager reviews and\napproves the request"/]

    MgrApproval2 -- Rejected --> Rejected2(("Rejected"))
    MgrApproval2 -- Approved --> RiskCheck{"What is the\napplication's risk level?"}

    RiskCheck -- Low --> Fulfill
    RiskCheck -- "Medium or High" --> AISum["AI summarizes\nthe justification"]

    AISum --> ITCheck{"Is risk\nMedium or High?"}
    ITCheck -- Yes --> ITApproval2[/"IT / application owner\nreviews the request"/]
    ITCheck -- "No (already ruled out above)" --> Fulfill

    ITApproval2 -- Rejected --> Rejected2
    ITApproval2 -- Approved --> SecCheck{"Is risk High?"}

    SecCheck -- Yes --> SecApproval[/"Security reviews\nthe request"/]
    SecCheck -- "No (Medium)" --> Fulfill

    SecApproval -- Rejected --> Rejected2
    SecApproval -- Approved --> Fulfill

    Fulfill{{"Create IT fulfillment\ntask in Jira"}}
    Fulfill -- "Fails, under 3 attempts" --> FulfillWait["Wait, then retry\n(with backoff)"] --> Fulfill
    Fulfill -- "Fails, 3 attempts used up" --> Failed2
    Fulfill -- Succeeds --> Notify

    Notify{{"Notify employee via Slack"}}
    Notify -- Fails --> Continue2["Notification failed —\nworkflow continues anyway"]
    Notify -- Succeeds --> Complete2(["Completed"])
    Continue2 --> Complete2
```

**Step key reference:** Validate = `validate_request` · Manager review = `manager_approval` · AI summary = `summarize_justification` · IT review = `it_approval` · Security review = `security_approval` · Jira = `create_fulfillment_task` · Slack = `notify_employee`

## Approval chain by risk tier (Workflow 2)

| Risk level | Approvals required |
|---|---|
| Low | Manager only |
| Medium | Manager + IT |
| High | Manager + IT + Security |

## Reading notes

- Diamonds are decisions the *engine* makes automatically (validation, retry checks, condition checks). Parallelogram boxes are the only points where the workflow pauses for an actual human decision.
- The "wait, then retry" boxes represent the instance moving to a `waiting_external` state — it genuinely stops running until the worker process (`app/workers/runner.py`) picks the retry back up on its next poll (every 3s).
- The two "Failed" boxes per diagram are the same end state reached by different causes (bad input vs. exhausted retries) — reused deliberately, not a diagram bug.
