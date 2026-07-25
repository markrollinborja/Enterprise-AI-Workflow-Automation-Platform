# ADR-0004: Business Rules as Testable Code, Not a DB-Editable Table

**Status:** Accepted — 2026-07-23

**Context:** The spec's original model list includes a `BusinessRule` table, implying rules are data that could be edited without a deployment.

**Decision:** Rules live as pure functions/config in `services/rules`, covered by unit tests, deployed as code.

**Alternatives considered:** DB-stored rules with a rules-admin UI — rejected: nobody is building that admin UI in V1, and a `BusinessRule` table with no editor is just a worse version of a Python function (harder to test, harder to version-control, harder to review in a PR).

**Consequences:** Changing a rule requires a code change + tests + deploy, not a runtime edit — correct tradeoff for a system where rule correctness (who needs to approve, what counts as high-risk) has real consequences and should go through the same review process as any other logic change. Rules stay unit-testable in isolation (pure functions, no DB, no mocking) which directly satisfies the spec's "rules separate from routing code, testable" requirement.
