# ADR-0015: Dual-Mode Authentication — Local JWT and Keycloak OIDC Behind One Interface

**Status:** Accepted — 2026-08-10

**Context:** V2 Module 4 requires Keycloak as a real identity provider: OIDC authorization-code flow with PKCE, token validation against issuer/audience/signature via JWKS, and role mapping from token claims. V1 (ADR-0006) authenticates locally — this app owns password hashes, signs its own HS256 tokens with `JWT_SECRET_KEY`, and reads roles from `users.role`. It is both identity provider and resource server.

These collide in four places. Password storage becomes vestigial. Verification changes from HMAC-with-shared-secret to RSA-against-a-rotating-public-key fetched over HTTP. Nearly all 193 backend tests authenticate by calling `/auth/login` for a local token. And — the consequential one — moving token issuance to Keycloak would make every authenticated test require a running Keycloak container.

That last point is the crux. The V1 suite needs only PostgreSQL. That property is why it can be run anywhere in seconds, and it is the reason the suite gets run at all. A test suite that requires a container stack is a test suite that stops being run.

**Decision:** Authentication is a swappable provider selected by `AUTH_MODE=local|oidc`. Both implementations resolve to the same `get_current_user` dependency and return the same principal, so the authorization layer, route dependencies, and RBAC checks are identical under either mode and are written once.

- `AUTH_MODE=local` — V1's behavior, unchanged. Used by the test suite and by anyone who wants to run the app without an identity stack. Keeps tests hermetic and CI fast.
- `AUTH_MODE=oidc` — full authorization-code flow with PKCE against Keycloak, per-request validation of signature, issuer, and audience against the JWKS endpoint, roles mapped from token claims. This is the mode the demo and the compose `identity` profile run.

This is the same adapter pattern every other V2 provider uses (ADR-0016): one interface, a live implementation and an alternative, both satisfying the same contract tests.

**Alternatives considered:**

*Replace local JWT entirely with Keycloak* — rejected. Cleanest single narrative, and genuinely the "right" production answer, but it forces a Keycloak container into every test run and rewrites the login helper behind ~190 tests. The cost is paid on every future test run by every future phase; the benefit is a marginally simpler story. Deliberate trade of narrative tidiness for a fast, dependency-light suite.

*Keycloak at login only, backend continues issuing its own session token* — rejected. Minimal disruption, but it validates a Keycloak token exactly once and then falls back to self-issued tokens, so per-request JWKS validation — the part that actually demonstrates OIDC resource-server behavior — never happens. Weaker demonstration for identity-adjacent roles, which is precisely the audience this module exists for.

**Consequences:**

Two authentication paths exist and both must be maintained. The real risk is drift: the modes agreeing on authentication but diverging on authorization. Mitigated by a test that runs identical RBAC assertions through both modes and requires identical decisions — that test is the contract, and it is worth more than either implementation.

The V1 suite keeps running with only PostgreSQL, so CI stays fast and the suite stays runnable in constrained environments.

Nothing about Module 4's requirements is weakened: PKCE, JWKS validation, issuer and audience checks, and claim-based role mapping all genuinely happen in `oidc` mode. The honest interview framing is "authentication is a provider interface — local JWT for hermetic tests, Keycloak OIDC for the real flow, one authorization layer behind both," which demonstrates more thought than "I used Keycloak."

`AUTH_MODE` must never default to `local` in a deployed configuration. This decision therefore carries a required follow-up, to be implemented alongside the OIDC provider in Phase 3: startup validation that refuses to boot with `AUTH_MODE=local` when `ENVIRONMENT` is anything other than local or test. Until that exists, the safeguard is documentation only — recorded here as an obligation, not as a shipped control.
