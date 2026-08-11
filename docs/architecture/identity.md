# Identity and Authentication

Two authentication mechanisms, one authorization layer. See ADR-0015 for why.

```
AUTH_MODE=local                          AUTH_MODE=oidc
──────────────                           ──────────────
POST /auth/login                         Browser → Keycloak login
  ↓ bcrypt check                           ↓ authorization code + PKCE
  ↓ sign HS256 JWT                         ↓ code exchanged for RS256 token
  ↓                                        ↓ signature/issuer/audience/expiry
  └──────────────► get_current_user ◄──────┘
                          ↓
                    require_role(...)
                          ↓
                       route
```

Everything below `get_current_user` is written once and cannot tell which
mode produced the user. `tests/test_auth_modes.py::TestRbacParity` runs the
same RBAC assertions through both and requires identical decisions — that
test is the contract, and it is worth more than either implementation.

---

## Running each mode

**Local (default).** Nothing to start beyond the base stack.

```bash
docker compose up
```

Demo users are seeded by `backend/app/db/seed.py`; the shared password is
`MeridianDemo123!`.

**OIDC.**

```bash
docker compose --profile identity up -d      # adds Keycloak
```

Then set in `.env` and restart the backend:

```
AUTH_MODE=oidc
OIDC_ISSUER=http://localhost:8080/realms/meridian
```

No client secret to set — `meridian-flow` is a public client (ADR-0019). The
frontend redirects the browser to Keycloak and performs the code-for-token
exchange itself, using PKCE rather than a secret it could never actually
keep confidential once shipped to every browser that loads the page.

Keycloak admin console: <http://localhost:8080> (`admin` / `admin`).

**Changed `infra/keycloak/realm-meridian.json`?** `docker compose restart
keycloak` is not enough — Keycloak's dev-mode database lives inside the
container's own writable layer, not a volume, so a plain restart reuses the
same container and the same already-imported realm; your JSON edit is
silently ignored. Recreate it instead:

```bash
docker compose up -d --force-recreate keycloak
```

Found the hard way: after editing the realm file for ADR-0019, a `restart`
left the client confidential and every login failed with a 401 from
Keycloak's token endpoint until the container was actually recreated.

The realm ships six users mirroring the local seed, same addresses, same
password, same roles — so switching modes shows the same application with a
different login screen rather than a different dataset.

| User | Meridian role |
|---|---|
| ava.thompson@cordant.io | HR |
| marcus.reed@cordant.io | Manager |
| priya.nair@cordant.io | IT |
| daniel.okafor@cordant.io | Security |
| sofia.alvarez@cordant.io | Employee |
| admin@cordant.io | Administrator |

---

## The startup guard

`AUTH_MODE=local` is refused unless `ENVIRONMENT` is `local`, `test`, or `ci`.
The container will not boot otherwise.

This exists because the failure it prevents has **no runtime symptom**.
`local` has to be the default — the test suite and a fresh clone both depend
on it — so a deployment that forgets to set `AUTH_MODE` silently inherits
self-issued tokens signed with whatever `JWT_SECRET_KEY` happens to be set.
Every login still works. Nothing looks wrong. A container that refuses to
start is the only signal that cannot be missed.

The environment allowlist is an allowlist deliberately: a new environment
name added later inherits the strict behavior rather than the permissive one.

---

## What OIDC validation actually checks

Four checks. Skipping any one is a real vulnerability, not a missing nicety.

**Signature**, against Keycloak's JWKS. Without it, a token is a JSON object
anyone can write.

**Issuer**, exactly matching the configured realm. Without it, a token from
*any* Keycloak realm — including one an attacker runs — is accepted.

**Audience**, matching our client. Without it, a token minted for a different
client in the same realm works here. This is token substitution, and it is
the check most often skipped in the wild: Keycloak only populates `aud` when
an audience mapper is configured, so validation appears broken and gets
turned off instead of fixed. `infra/keycloak/realm-meridian.json` configures
the mapper, which is what makes the check possible.

**Expiry**, with 30 seconds of leeway for container clock drift.

Plus one rejection before any verification runs: **only asymmetric algorithms
are accepted**. Accepting HS256 alongside RS256 enables algorithm confusion —
an attacker signs a token using the *public* key as an HMAC secret, and a
verifier that trusts the header's `alg` accepts it.

### Two addresses for one Keycloak

`OIDC_ISSUER` has to be `http://localhost:8080/realms/meridian` — it must
match every token's `iss` claim exactly, and the browser mints tokens
against `localhost:8080`. But the backend derives its JWKS fetch URL from
that same issuer by default, and inside the backend's own container
`localhost` means the backend container, not the host — there is nothing
listening on port 8080 there. The browser and the backend need to reach one
Keycloak through two different addresses.

`OIDC_JWKS_URI` (`Settings.oidc_jwks_uri`) exists to break that dependency:
when set, the backend fetches keys from it instead of deriving the URL from
`OIDC_ISSUER`. `docker-compose.yml` sets it to
`http://keycloak:8080/realms/meridian/protocol/openid-connect/certs` for the
backend service — the compose network's service name, not `localhost` —
while `OIDC_ISSUER` stays the browser-facing value everywhere. Found by
running the actual authorization-code flow end to end and watching the
backend return 503 `IdentityProviderUnavailableError` on a token Keycloak
had just issued correctly: the token was fine, the container couldn't reach
the address it was told to use.

### JWKS caching

Cached for 300 seconds, because fetching per request puts Keycloak in the hot
path of every authenticated call. Expiring, because Keycloak rotates signing
keys and a cache that never expires turns a routine rotation into a total
authentication outage.

An unknown `kid` triggers exactly **one** refetch — that is what makes
rotation recover in seconds instead of waiting out the TTL. Bounded at one,
because without the bound a token carrying a garbage `kid` would trigger a
JWKS fetch per request, turning a malformed token into a denial of service
aimed at Keycloak.

### Failure modes are distinguished

| Situation | Response |
|---|---|
| Bad/expired/forged token | 401 |
| Keycloak unreachable | **503** |
| Valid token, no Meridian role | 403 |
| Valid token, no provisioned account | 401 |
| Valid token, account deactivated | 403 |

Keycloak being down returns 503, not 401. Telling users their credentials are
invalid during an IdP outage sends them off to reset passwords that were
never the problem, and hides the outage behind a wall of auth failures.

---

## Role mapping

Keycloak roles are prefixed `meridian-` to avoid colliding with Keycloak's
own built-ins (`offline_access`, `uma_authorization`, `default-roles-*`),
which every user carries and none of which mean anything here.

Two behaviors worth knowing:

**No mapped role means no access** — the mapper returns `None` rather than
defaulting to `employee`. Defaulting would silently grant every user in the
realm a working Meridian account.

**Highest role wins.** A user holding both `meridian-manager` and
`meridian-administrator` gets administrator, not whichever came first out of
an unordered claim.

In OIDC mode **the token's roles are authoritative**, and the local row is
updated to match on each request. Keycloak is the source of truth for
authorization in that mode, so a role revoked there takes effect on the next
request rather than whenever someone remembers to update the database.

---

## OIDC authenticates; SCIM provisions

A token for a user this platform has never heard of is **rejected, not turned
into an account**. Just-in-time provisioning on login would mean anyone
Keycloak trusts becomes a Meridian user with whatever role their token
claims — bypassing the provisioning path entirely, making SCIM decorative,
and leaving account creation with no audit trail ("who created this user?"
would answer "they logged in once").

The cost is that a Keycloak user must be provisioned before first sign-in,
which is exactly how a real SCIM-backed deployment behaves. See
[scim.md](scim.md).

First login for a seeded user matches on email (case-insensitively) and then
writes the external-identity mapping, so later logins take the stable path
that survives an email change upstream.

---

## The frontend flow

`GET /auth/mode` is public and unauthenticated — the login screen calls it
before rendering anything, because it has to decide between a password form
and a "Continue with Keycloak" button before the person has any credentials
to offer. `POST /auth/login` checks the same setting server-side and refuses
with 403 if the deployment is in `oidc` mode, rather than minting a local
token that would validate against neither checker.

`frontend/src/api/oidc.ts` generates the PKCE verifier and challenge,
redirects to Keycloak, and — on return to `/auth/callback` — exchanges the
code for a token directly against Keycloak's token endpoint, with no secret
involved (ADR-0019). `frontend/src/components/OidcCallback.tsx` hands the
resulting token to `AuthContext.loginWithToken`, the same entry point a
local-mode login uses after `POST /auth/login` — from that point on,
neither `AuthContext` nor any component downstream of it can tell which
mode produced the token.

`/auth/callback` is a real HTTP redirect target, not an in-app navigation —
this app deliberately has no router (see the comment in `App.tsx`), so
`frontend/nginx.conf` adds an SPA fallback (`try_files ... /index.html`)
specifically so that path resolves to the app instead of a bare 404, and
`AppShell` checks `window.location.pathname` directly to render
`OidcCallback` before the normal login/authenticated-view branch.

---

## What is verified

| Component | Status |
|---|---|
| Startup guard, all environments | **Tested** |
| Token validation — signature, issuer, audience, expiry, algorithm confusion, unknown key | **Tested** against real RSA signatures and a fake JWKS |
| Role mapping and precedence | **Tested** |
| User resolution, linking, deactivation | **Tested** |
| RBAC parity between modes | **Tested** across all six roles |
| Keycloak container boots and imports the realm | **Verified** — realm, all 6 users, all 6 realm roles confirmed in the admin console |
| Authorization-code + PKCE protocol, driven manually through a browser against the running backend | **Verified** — real login as ava.thompson@cordant.io through Keycloak's hosted form, real RS256 token, `GET /auth/me` returns `role: "hr"`, `GET /employees` returns 200 |
| The same flow through the app's own login screen (`LoginForm` → Keycloak → `OidcCallback`) | **Verified** — clicked "Continue with Keycloak" on the actual login page, signed in as ava.thompson@cordant.io through Keycloak's hosted form, landed on the authenticated dashboard with her name, HR role, and live employee data |

Driving the actual protocol against the running containers — not just
inspecting the code — is what caught three real bugs before every row above
turned green: the backend could not reach Keycloak's JWKS endpoint over the
compose network until `OIDC_JWKS_URI` was added; the client secret embedded
in the frontend made the case for the public-client redesign in ADR-0019;
and after that redesign, `docker compose restart keycloak` turned out not
to actually apply it, because Keycloak's dev database survives a restart
(see "Changed realm-meridian.json?" above) — the fix looked correct in the
repo and still failed until the container was properly recreated.

---

## Known simplifications

- `start-dev` mode, in-memory H2, HTTP only. Not production Keycloak.
- No refresh-token rotation or back-channel (RP-initiated) logout yet —
  `logout()` in `AuthContext` clears the local token but does not end the
  Keycloak session, so a browser that still has that session cookie will
  skip straight through Keycloak's login form on the next "Continue with
  Keycloak" click rather than prompting again.
- No silent/background token renewal. An access token that expires
  mid-session requires signing in again rather than refreshing invisibly.
- No frontend build-time OIDC configuration beyond sensible localhost
  defaults (`frontend/src/api/oidc.ts`) — a deployment against a real
  Keycloak host would set `VITE_OIDC_ISSUER` etc. at build time, the same
  way `VITE_API_BASE_URL` already works.
- No `state`-replay protection beyond one-time use via sessionStorage —
  adequate for this platform's threat model, not a hardened production
  implementation.
- SAML remains a proof of concept to be added after OIDC is stable.
