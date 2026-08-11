# SAML PoC

`GET /auth/saml/login` and `POST /auth/saml/acs` — a proof-of-concept SAML
2.0 service provider, not a third `AUTH_MODE`. See ADR-0021 for why: OIDC
(`docs/architecture/identity.md`) is this deployment's real sign-in path;
this route pair exists to prove SP-side signed-assertion handling works end
to end, using the same Keycloak realm as a second protocol rather than a
second identity provider.

---

## Requires AUTH_MODE=local

This route pair issues a local-format token (below), which
`get_current_user` only accepts when the deployment is running
`AUTH_MODE=local` (ADR-0015, ADR-0021). `GET /auth/saml/login` checks this
first and refuses immediately with a clear error if the deployment is in
oidc mode; the login screen hides the "Try the SAML PoC" link entirely
outside local mode for the same reason. This was found by actually driving
the flow through a browser against an oidc-mode deployment — the login and
the full Keycloak round trip genuinely succeeded, and it failed one step
later at `/auth/me` with no obvious cause, before the guard existed.

---

## The flow

1. Someone clicks "Try the SAML PoC" on the login screen (`LoginForm.tsx`),
   a plain link to `GET /auth/saml/login` — a full page navigation, not a
   fetch, the same way the Keycloak OIDC button works.
2. The backend (`app/api/routes/saml.py`) fetches Keycloak's SAML IdP
   metadata (cached — see `SAMLIdPMetadataCache` in `app/core/saml.py`),
   builds an `AuthnRequest`, and 302-redirects the browser to Keycloak's
   SSO endpoint with it (HTTP-Redirect binding: DEFLATE, base64, URL
   parameter).
3. Keycloak authenticates the user against the same realm OIDC uses
   (`infra/keycloak/realm-meridian.json`'s demo users) and POSTs a signed
   `SAMLResponse` back to `POST /auth/saml/acs` (HTTP-POST binding).
4. The backend validates the response (`SAMLValidator.validate_response`,
   documented in full in its module docstring and in ADR-0021), resolves a
   local `User` by NameID/email (`app/services/auth/saml_resolver.py`,
   no just-in-time provisioning — same rule as OIDC), and issues a token in
   the same local-JWT format `AUTH_MODE=local` already validates.
5. The backend 302-redirects the browser to
   `http://localhost:5173/auth/saml/callback?token=...`.
6. `SamlCallback.tsx` reads the token from the URL, hands it to
   `AuthContext.loginWithToken` — the same entry point local-mode login and
   OIDC login both use — and scrubs the URL.

Unlike the OIDC callback, there is no token exchange happening in step 6:
the backend already did the security-critical work server-side before
redirecting, so the frontend's job here is strictly simpler than
`OidcCallback.tsx`'s PKCE code-for-token exchange.

---

## Security controls

Full reasoning in `app/core/saml.py`'s module docstring and ADR-0021.
Summary:

| Control | What it prevents |
|---|---|
| Exactly one `<saml:Assertion>`, checked before signature verification | XML Signature Wrapping via a second, attacker-supplied assertion |
| Claims read only from signxml's verified `.signed_xml`, never the raw parsed tree | The other half of the wrapping defense |
| Signature verified against Keycloak's published signing certificate (fetched from its SAML metadata, cached) | A self-signed or unsigned assertion |
| `Audience` must match this SP's entity id | An assertion issued for a different SAML client in the same realm |
| `SubjectConfirmationData/@Recipient` must match the ACS URL exactly | A captured assertion replayed against a different SP |
| `InResponseTo` checked against a one-time-use store of AuthnRequest ids this process issued | IdP-initiated or forged responses; replay of a captured response |
| `Conditions` NotBefore/NotOnOrAfter, with leeway | Expired or not-yet-valid assertions |
| Assertion `Issuer` must match the configured Keycloak realm | Assertions asserting to be from this IdP but issued elsewhere |

---

## Mock vs. live

There is no mock mode here — unlike the MCP tools, this route pair always
talks to a real Keycloak (identity profile: `docker compose --profile
identity up -d`). There is nothing to simulate: the entire point is
proving the signed-assertion handshake against a real IdP.

---

## Why signxml, not python3-saml or pysaml2

Both of the more common Python SAML toolkits depend on `xmlsec1`, a C
library requiring its own native build in the image. signxml verifies and
produces XML-DSig signatures in pure Python on `lxml` + `cryptography`,
both already dependencies elsewhere in this project. See ADR-0021 for the
full reasoning, including why this holds up as a real engineering choice
independent of any one environment's tooling constraints.

---

## What is verified

| Component | Status |
|---|---|
| AuthnRequest construction, HTTP-Redirect binding encoding | **Tested** (`backend/tests/test_saml.py`) |
| Signature verification, wrapping-attack resistance, replay protection, audience/recipient/issuer/conditions checks | **Tested** (`backend/tests/test_saml.py`, 22 cases) |
| `/auth/saml/login` and `/auth/saml/acs` wired together against a real database | **Tested** (`backend/tests/test_saml_routes.py`) |
| Full SP-initiated login through a real Keycloak, driven by an actual browser | See the phase closeout notes once run — mirrors how OIDC's three real bugs were only found by driving the actual UI (`docs/architecture/identity.md`, "What is verified") |

---

## Known simplifications

- No SP metadata endpoint. The ACS URL is configured directly on the
  Keycloak client (`infra/keycloak/realm-meridian.json`) rather than
  discovered — reasonable for one hardcoded IdP relationship.
- `_PendingRequestStore` (the InResponseTo replay guard) is in-process
  memory, not shared storage — would need hardening for multiple backend
  replicas. Acceptable because this route pair is never `AUTH_MODE`'s
  dispatch target.
- Assertion-signed, not response-signed (`saml.server.signature=false` on
  the Keycloak client) — every security-relevant claim lives inside the
  signed Assertion regardless; see ADR-0021 for why this is a defensible
  configuration, not a corner cut.
- No encrypted assertions, no single logout, no metadata-based SP
  autoconfiguration — out of scope for a PoC proving the core handshake.
- Same `start-dev`/H2/HTTP-only Keycloak simplifications already documented
  in `docs/architecture/identity.md` apply here too — same realm, same
  container.
