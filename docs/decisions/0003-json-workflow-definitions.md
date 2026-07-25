# ADR-0003: Workflow Definitions as Versioned JSON, Not Relational Step Tables

**Status:** Accepted — 2026-07-23

**Context:** The spec's original model list includes `WorkflowStepDefinition` as a table, implying steps are normalized rows editable via CRUD — the shape a drag-and-drop workflow-builder UI would need.

**Decision:** A `WorkflowDefinition.definition_json` column holds the full step list, conditions, approval requirements, and failure behavior for that workflow, versioned by bumping `WorkflowDefinition.version`. Files in `workflows/*.json` are the source of truth, loaded into the DB at seed/startup time.

**Alternatives considered:** Relational step definitions (`WorkflowStepDefinition` table with FK-linked conditions/actions) — rejected: this is the schema a visual workflow designer needs, and V1 explicitly excludes a drag-and-drop builder (spec section 23). Building the relational model without the UI that justifies it is complexity with no consumer.

**Consequences:** Editing a workflow means editing a JSON file and redeploying/reseeding, not clicking through an admin UI — acceptable and expected for V1. If a V2 visual builder is ever built, `definition_json`'s schema is the contract that builder would need to produce; the runtime engine wouldn't need to change, only how the JSON gets authored.
