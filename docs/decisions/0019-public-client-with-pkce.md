# ADR-0019: The Frontend Uses a Public Keycloak Client with PKCE, Not a Confidential Client

**Status:** Accepted — 2026-08-11

**Context:** The Phase 3 realm export configured `meridian-flow` as a confidential client — `publicClient: false`, with a client secret (`meridian-local-dev-client-secret`) — under the assumption that something server-side would perform the authorization-code exchange. That assumption turned out to be wrong: nothing in this platform's design has the backend sit in the middle of a browser login. The frontend is a single-page app; it redirects the browser to Keycloak and receives the redirect back directly. Any code that exchanges the authorization code for a token runs in the browser.

Verifying the flow end to end (see docs/architecture/identity.md) surfaced the consequence directly: making the code-for-token exchange work from the frontend meant either embedding the confidential client's secret in the React bundle, or standing up a backend endpoint whose only job was to proxy that one call. The first defeats the purpose of a secret — anyone can read it out of the built JS or the network tab, so it is not actually confidential once shipped to a browser. The second adds a component, a route, and a request hop to solve a problem OAuth already has a standard answer for.

**Decision:** `meridian-flow` is a public client (`publicClient: true`, no secret). Proof of possession comes entirely from PKCE (RFC 7636) — the frontend generates a code verifier, sends its SHA-256 challenge with the authorization request, and presents the verifier on the token exchange. This is precisely the case PKCE was designed for: a client that cannot hold a secret.

Consequently:

- `Settings.oidc_client_secret` is removed from the backend. Grepping the codebase before removing it confirmed what the architecture implies: the backend never used it for anything. It only ever appeared in the OIDC-mode startup-configuration check (`validate_auth_configuration`), which is now updated to stop requiring it — a requirement for a value nothing consumes is worse than no requirement, because it invites inventing a placeholder to satisfy a check that means nothing.
- `directAccessGrantsEnabled` stays `false` on the client. Public-client status does not imply the resource-owner-password grant should be open; the browser must go through the real redirect + PKCE flow.
- The code-for-token exchange happens directly from the browser to Keycloak's token endpoint. This is the one OIDC call that is not proxied through the backend, and it is the correct one not to proxy: the backend has nothing to add to it (no secret to attach, no server-side session to create), and proxying it would only add a hop.

**Alternatives considered:**

*Keep the confidential client; add a backend token-exchange endpoint (BFF pattern)* — this is the standard fix when a real secret must stay server-side, and it is the right call for platforms that also want to keep the access token out of the browser entirely (e.g. via an HttpOnly session cookie). Rejected here because the resulting security posture is roughly equivalent for this platform's threat model — the token still ends up usable from JavaScript either way, since `AuthContext` already stores the local-mode token in `localStorage` and every other route treats a bearer token as the unit of authentication — while a BFF proxy is a real component this project would then have to build, test, and explain, for a security property (hiding a secret) that has nothing behind it to hide. Worth revisiting if session-cookie-based auth is ever adopted platform-wide; not proportionate to adopt for OIDC alone while local-mode auth stays bearer-token-in-localStorage.

*Embed the confidential secret in the frontend bundle* — rejected outright. A secret shipped to every browser that loads the page is not a secret; this would be the interview question "why is there a client secret in your JS bundle" with no good answer.

**Consequences:**

The authorization code returned to `/auth/callback` is a single-use, short-lived credential good for one PKCE-verified exchange — the security property that matters here does not depend on the client also presenting a secret.

Anyone with the compiled frontend (i.e. anyone) can see `client_id` and construct an authorization request. This is normal and expected for a public client; it is not a vulnerability, because PKCE — not client secrecy — is what prevents an intercepted authorization code from being redeemed by anyone other than the party that generated the matching code verifier.

`.env.example` and `docker-compose.yml` no longer reference `OIDC_CLIENT_SECRET`. Anyone extending this platform with a genuine backend-mediated OAuth flow (e.g. a future server-to-server integration) should give that flow its own confidential client, not resurrect this one — a client's public/confidential status should match how it is actually used, not be chosen once and left stale as the architecture around it changes.
