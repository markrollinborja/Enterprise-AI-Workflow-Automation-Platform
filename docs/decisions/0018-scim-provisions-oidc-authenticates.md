# ADR-0018: SCIM Provisions, OIDC Authenticates — No Just-in-Time User Creation

**Status:** Accepted — 2026-08-10

**Context:** Module 4 (Keycloak OIDC) and Module 5 (SCIM) both create a relationship between an external identity and a Meridian `User`. The obvious convenience is just-in-time provisioning: when a valid token arrives for someone with no local account, create one from the token's claims. Most tutorials do this, and it makes the first login of a new employee work with no setup.

It also makes SCIM decorative. If logging in creates an account, the provisioning endpoint is a redundant second path to the same outcome, and the interesting half of Module 5 — deprovisioning, role assignment, reconciliation — is demonstrating something the platform does not actually depend on.

There is a security argument underneath the architectural one. With JIT provisioning, anyone Keycloak will issue a token for becomes a Meridian user carrying whatever role their token claims. The blast radius of a misconfigured Keycloak group mapping, or of a realm shared with another application, stops being "someone gets a login error" and becomes "someone gets an account with a role nobody granted".

And it destroys the audit trail. "Who created this user, and when, and on whose authority?" answers "they logged in once", which is not an answer.

**Decision:** OIDC authenticates an identity. SCIM provisions the account. They do not overlap.

- A valid token for an unprovisioned identity is **rejected** (401), not turned into an account. The rejection is logged with the OIDC subject — never the email — so an unprovisioned login attempt is investigable without writing an unknown person's address into our logs.
- Account creation, role assignment, and deactivation happen only through `/scim/v2/Users`, which has its own credential and its own audit trail.
- First login of an already-provisioned user matches on email case-insensitively and writes the external-identity mapping, so subsequent logins use the stable identifier that survives an upstream email change.
- In `oidc` mode the token's roles are authoritative on every request. Keycloak is the source of truth for authorization there, so a revoked role takes effect on the next request rather than whenever someone remembers to update the database. The local row still governs whether the account exists and is active.

**Alternatives considered:**

*Just-in-time provisioning on first login* — rejected for the three reasons above. It is genuinely more convenient and it is what most examples show; the cost is that provisioning stops being a real subsystem and account creation stops being auditable.

*JIT provisioning restricted to a role-carrying token* — rejected as a middle ground that keeps the audit problem while adding a subtle one: the account's role would then be whatever the token said at first login, frozen, with no record of who decided it.

*Deleting users on SCIM DELETE rather than deactivating* — rejected. It would orphan every approval, workflow, and audit row naming that user, which is exactly the history needed when asking what a departed employee had access to. `DELETE` returns 204 and sets `active: false`; well-behaved connectors are satisfied and the record survives.

**Consequences:**

A Keycloak user must be provisioned before they can sign in. That is a real operational constraint and it is also exactly how a SCIM-backed deployment behaves in practice — the directory pushes the account, then the person logs in.

For the demo this means the realm's six users must exist in both Keycloak and the Meridian database. The seed script and `infra/keycloak/realm-meridian.json` deliberately use the same six identities so that switching `AUTH_MODE` shows the same application rather than an empty one.

Deactivation is enforced in two places — Keycloak and the resource server. That is redundant on purpose: a token issued minutes before deprovisioning remains cryptographically valid until it expires, so the identity provider alone cannot revoke access promptly.

The SCIM bearer token becomes a high-value credential: it can create accounts and assign roles. It is deliberately separate from every other secret in the system so it can be rotated on its own, and a blank value rejects all requests rather than disabling the check.
