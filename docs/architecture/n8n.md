# n8n Integration

**Status:** service definition, version-controlled workflow export, and the
backend ingestion endpoint are implemented and tested. The n8n container itself
has **not** been booted and the workflow has **not** been executed — see
[What is verified](#what-is-verified).

---

## Why n8n is in this architecture at all

A fair challenge: Meridian Flow already has a workflow engine. Why add another?

They do different jobs, and the split is the point.

- **n8n owns the messy edge.** Receiving a provider's webhook, validating and
  normalizing its payload, minting a correlation ID and a stable idempotency
  key, retrying a flaky call, sending a Slack update. Work that changes often,
  benefits from being visual, and does not belong in application code.
- **Meridian owns the business transaction.** Approval chains, state
  transitions, RBAC, audit. Work that must be deterministic, tested, and
  reviewable in a pull request.

Putting approval logic in n8n would make it untestable and unversioned in any
meaningful sense. Putting webhook normalization in the backend would mean a
code change and a deploy every time a provider adjusts a field name.

The boundary is the ingestion endpoint: n8n sends one normalized, signed event;
Meridian decides what it means.

---

## Running it

n8n is behind an opt-in Compose profile. The base stack is unchanged:

```bash
docker compose up                          # V1's five services, as before
docker compose --profile integrations up   # adds n8n
```

The base stack stays at five services deliberately. Someone who clones this repo
should see the core platform work without booting tooling they did not ask for.

Editor UI: http://localhost:5678

**First run prompts you to create an instance owner account.** n8n removed
basic auth in v1.0 and made user management mandatory — `N8N_BASIC_AUTH_ACTIVE`
and friends are silently ignored on 1.x, which is why this compose file does not
set them. A variable that looks like a security control but does nothing is
worse than no variable at all.

The owner account is local, stored in the `n8n_data` Docker volume, and survives
restarts. It is not a signup for anything external. If you ever `docker compose
down -v`, the volume goes with it and you will be asked to create the account
again — along with losing any workflow you imported but did not export back to
`integrations/n8n/workflows/`.

For a fully hands-off setup, n8n supports pre-provisioning the owner via
`N8N_INSTANCE_OWNER_MANAGED_BY_ENV` with a **bcrypt-hashed** password. Not used
here: it adds a hash-generation step to the README for a local dev tool, and a
plaintext value in that variable breaks login in a way whose error message does
not point at the cause.

---

## Importing the workflow

Exports live in `integrations/n8n/workflows/` and are mounted read-only at
`/workflows` inside the container. Read-only so an accidental edit in the UI
cannot rewrite the file the repository considers authoritative.

1. Open http://localhost:5678
2. **Workflows → Import from File**
3. Choose `/workflows/customer-onboarding.json`
4. Activate the workflow

Import is a documented manual step rather than an automatic overwrite on boot:
silently replacing whatever someone was editing is a bad default.

**Export after changing anything.** A workflow edited only in the UI exists on
one machine and in one Docker volume. Download the JSON and commit it, or the
repository stops being the source of truth.

---

## The customer-onboarding workflow

```
Salesforce webhook
  → validate (IsWon true, AccountId present)
  → normalize + mint correlation ID and idempotency key
  → HMAC-sign the exact bytes
  → POST /inbound/events
  → branch on response
  → acknowledge Salesforce
```

Three decisions inside it are worth reading the code for:

**The idempotency key is derived, not random.** It is
`sf-opp-{OpportunityId}-{LastModifiedDate}`. Salesforce delivers at-least-once,
so a retry of the same change must produce the *same* key or duplicate
protection cannot work. Including `LastModifiedDate` means a genuinely new
change to the same opportunity is correctly treated as a new event.

**The correlation ID is minted here** because this is the true edge of the
transaction. Everything downstream — Meridian, Jira, Slack — carries it, which
is what makes the whole flow searchable from one string. Meridian prefers the
caller's ID over its own for exactly this reason.

**The body is signed as a frozen string.** The Code node serializes once, signs
those bytes, and the HTTP node sends that same string verbatim. Signing an
object and letting the HTTP node re-serialize would change key order or
whitespace and produce a signature the backend cannot reproduce — an
intermittent 401 that is genuinely unpleasant to diagnose.

**Failures do not echo response bodies into Slack.** A provider error body can
carry tokens or customer data, and a Slack channel is a long-lived, widely
readable store. The alert carries a status code and a correlation ID; the full
redacted record lives in Meridian's support console.

---

## The contract n8n must satisfy

`POST /inbound/events`

| Header | Required | Notes |
|---|---|---|
| `X-Signature` | yes | HMAC-SHA256 hex of the raw body, `sha256=` prefix optional |
| `X-Idempotency-Key` | yes | Stable across retries of the same change |
| `X-Event-Type` | yes | `organization.onboarding_requested` today |
| `X-Correlation-ID` | no | Preferred over a generated one when present |

Body:

```json
{
  "correlation_id": "n8n-1234-006xx000004TmiQ",
  "account": { "id": "001xx000003DGb2AAG", "name": "Cordant Industries", "website": "https://cordant.io" },
  "opportunity": { "id": "006xx000004TmiQ", "is_won": true }
}
```

Responses:

| Code | Meaning |
|---|---|
| `200` | Accepted and processed |
| `208` | Duplicate — already processed, no action taken |
| `400` | Missing required header, or body is not a JSON object |
| `401` | Signature verification failed |
| `413` | Payload over 256 KB |
| `422` | Well-formed but missing `account.id` / `account.name` — recorded as FAILED and available for investigation |

**208 is a success.** A sender retrying because it never saw our acknowledgement
is behaving correctly. Answering with an error would push a well-behaved
integration into its failure path.

---

## Security

- HMAC-SHA256 over the **raw bytes**, verified before the body is parsed.
  Deserializing an unverified payload means running a parser on
  attacker-controlled input — the code you least want to reach first.
- Compared with `hmac.compare_digest`, so response timing does not leak how much
  of a guess was correct.
- An **unset secret rejects everything**. It is never treated as "verification
  disabled" — that is the failure mode that turns a config mistake into an open
  endpoint.
- Size is checked before signature verification: HMAC over an unbounded body is
  an easy way to burn CPU on a request that was never going to be accepted.
- Every failure mode returns the same message, so probing cannot distinguish
  "not configured" from "wrong signature".
- n8n's own editor is protected by its built-in user management (owner account
  on first run). That is adequate for a local development instance bound to
  localhost and is **not** a production access control. Anything exposed beyond
  localhost needs a reverse proxy with real authentication in front of it.

---

## What is verified

| Component | Status |
|---|---|
| `POST /inbound/events` — signature, idempotency, validation, organization creation | **Tested** — 30 automated tests |
| Compose service definition and profile | **Verified** — base stack confirmed unchanged at five services |
| Workflow JSON | **Verified** — parses, no dangling node connections |
| n8n container boots | **Verified 2026-08-10** — `n8n ready on 0.0.0.0, port 5678`, six containers running |
| Workflow imports and renders | **Verified 2026-08-10** — all 9 nodes load with correct types, no unknown-node errors, all connections intact |
| Workflow executes end to end against a live Salesforce org | **Not verified** |

The last row requires a Salesforce org configured to send outbound events and is
not claimed as working until someone has run it and recorded the result.

---

## Version pinning and the 1.x security advisory

The image is pinned to `1.121.0` as a **floor**, not a preference.

n8n versions **1.65 through 1.120.4** carry a published security advisory:
improper input validation in workflows that combine a Form Submission trigger
with a Form Ending node returning a binary file, allowing an unauthenticated
remote attacker read access to the underlying file system.

This project's workflows use no Form nodes, so that path is not exploitable
here — but a repository someone else will clone and run should not pin a
version with a known advisory against it. The original pin was `1.76.1`, which
sits inside the affected range; it was caught by n8n's own in-app update banner
during Phase 2 verification rather than by anything clever.

Bumping within 1.x is safe. Moving to 2.x is a deliberate migration rather than
a patch — node schemas change between majors and the workflow exports in
`integrations/n8n/workflows/` would need re-import and re-verification.

Advisory: <https://blog.n8n.io/security-advisory-20260108/>

---

## Known cosmetic issue

Importing into an already-open blank canvas keeps the canvas's name ("My
workflow") rather than the name inside the JSON ("Meridian — Customer
Onboarding"). The node graph and tags import correctly either way — only the
title differs. To get the intended name, import from the **Overview →
Workflows** list rather than from inside an open workflow, or rename it in the
editor.
