# ADR-0017: n8n Owns the Integration Edge, Meridian Owns the Business Transaction

**Status:** Accepted — 2026-08-10

**Context:** Meridian Flow already has a workflow engine (ADR-0002). Adding n8n invites the obvious question — why run a second orchestrator, and which one is in charge? Answered badly, this produces two systems that both half-own the same logic, and the resulting project reads as tool-collecting rather than architecture.

There is also a genuine engineering problem underneath it. The work at the provider boundary — receiving a webhook, normalizing a payload whose field names change when a Salesforce admin edits a page layout, minting identifiers, retrying a flaky call — changes far more often than approval rules do, and benefits from being visual and editable without a deploy. The work inside the business transaction — approval chains, state transitions, RBAC, audit — must be deterministic, unit-tested, and reviewable in a pull request. Those are different requirements and they pull in opposite directions.

**Decision:** A hard split with the ingestion endpoint as the boundary.

- **n8n owns the edge**: receive, validate shape, normalize vocabulary, mint the correlation ID and idempotency key, sign, deliver, alert on delivery failure.
- **Meridian owns the transaction**: what the event *means*, which approvals it requires, what state it moves to, who is allowed to see it, what gets audited.
- The interface between them is one signed HTTP call to `POST /inbound/events` carrying a normalized payload.

n8n never calls a business endpoint, never makes an approval decision, and never writes to the database. Meridian never parses a provider's native payload shape.

**Alternatives considered:**

*Backend receives Salesforce webhooks directly, no n8n* — rejected, though it is the simpler system. Every provider field-name change becomes a code change and a deploy, and the project loses a genuine demonstration of workflow-automation tooling that appears in most target job descriptions. It also puts untested, rapidly-changing normalization logic inside the tested core.

*n8n orchestrates the whole onboarding, including approvals* — rejected firmly. Approval logic in n8n is untestable in any meaningful sense, unreviewable in a pull request, and unversioned beyond a JSON blob. It would also make n8n a hard runtime dependency of the core product rather than an opt-in profile, which contradicts keeping the base stack runnable for someone who just cloned the repo.

*Message queue between the two instead of HTTP* — rejected as premature. A queue buys durability under backpressure that this system does not experience, and adds a broker to the compose stack. The idempotency key plus the sender's own retry already covers the failure it would address. Worth revisiting if inbound volume ever justifies it.

**Consequences:**

The correlation ID is minted at the true edge — in n8n, before Meridian is called — so a single string spans both systems' logs. Meridian deliberately prefers a caller-supplied correlation ID over its own generated one; overwriting it would break the join that is the entire point.

Duplicate protection lives in Meridian, not n8n, because Meridian owns the database and a unique constraint is the only place the guarantee can actually be enforced under concurrency. n8n's job is to produce a *stable* key; Meridian's job is to act on it exactly once.

n8n workflows are version-controlled as JSON exports (`integrations/n8n/workflows/`), which is weaker than code review of real source. A reviewer cannot meaningfully diff a node graph. Mitigated by keeping the workflows small and pushing anything with real logic behind the boundary into tested Python — if an n8n workflow ever needs a unit test, it is doing the wrong job.

n8n is an opt-in Compose profile. The base stack stays at V1's five services, so `docker compose up` still works for someone who has never heard of n8n.
