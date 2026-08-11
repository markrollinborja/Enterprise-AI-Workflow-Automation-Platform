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
OIDC_CLIENT_SECRET=meridian-local-dev-client-secret
```

Keycloak admin console: <http://localhost:8080> (`admin` / `admin`).

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

## What is verified

| Component | Status |
|---|---|
| Startup guard, all environments | **Tested** |
| Token validation — signature, issuer, audience, expiry, algorithm confusion, unknown key | **Tested** against real RSA signatures and a fake JWKS |
| Role mapping and precedence | **Tested** |
| User resolution, linking, deactivation | **Tested** |
| RBAC parity between modes | **Tested** across all six roles |
| Keycloak container boots and imports the realm | **Verified** — realm, all 6 users, all 6 realm roles confirmed in the admin console |
| Browser authorization-code + PKCE flow end to end | **Verified** — real login as ava.thompson@cordant.io through Keycloak's hosted form, real RS256 token, `GET /auth/me` returns `role: "hr"`, `GET /employees` returns 200 |

Verified by hand-driving the actual protocol (PKCE challenge, redirect to
Keycloak, real password login, code exchange, bearer call against the
running backend) through a browser — not by inspection. That process
surfaced two real bugs before this row could turn green: the frontend has
no OIDC UI yet (tracked separately — see "Known simplifications" below),
and the backend could not reach Keycloak's JWKS endpoint over the compose
network until `OIDC_JWKS_URI` was added (see "Two addresses for one
Keycloak" above).

---

## Known simplifications

- The frontend has no OIDC UI yet — no redirect-to-Keycloak, no
  `/auth/callback` route. Phase 3 scoped the backend (validation, RBAC
  parity, SCIM); the browser-based flow above was driven by hand, outside
  the app's UI, to verify the backend and Keycloak side independently of
  that gap. Building the frontend piece is tracked as its own follow-up.
- `start-dev` mode, in-memory H2, HTTP only. Not production Keycloak.
- The client secret is committed in the realm file and `.env.example`. It is
  a local development realm with fictional users, and the file is only useful
  if it works out of the box. A real deployment generates its own.
- No refresh-token rotation or back-channel logout yet.
- SAML remains a proof of concept to be added after OIDC is stable.
