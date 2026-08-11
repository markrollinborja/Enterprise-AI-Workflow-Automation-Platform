# SCIM 2.0 Provisioning

`/scim/v2/Users` — a deliberately narrow, fully documented subset of RFC 7643
and RFC 7644.

The scope is chosen around what provisioning connectors actually send. A
partial implementation that is honest about its boundaries is more useful
than a broad one that fails in undocumented ways.

---

## Supported

| Operation | Endpoint | Notes |
|---|---|---|
| Create user | `POST /Users` | Idempotent on `externalId` |
| Get user | `GET /Users/{id}` | |
| Find user | `GET /Users?filter=userName eq "x"` | The only supported filter |
| List users | `GET /Users?startIndex=&count=` | Paginated |
| Update user | `PATCH /Users/{id}` | `active`, `name`, `roles`, `userName` |
| Deprovision | `PATCH active:false` or `DELETE /Users/{id}` | Both deactivate |

## Not supported

Groups, bulk operations, `PUT /Users/{id}` (full replace), sorting, ETags /
`If-Match`, `/Me`, `/ResourceTypes`, `/Schemas`, `/ServiceProviderConfig`,
and any filter other than `userName eq`.

Absent by decision, not omission. Each would be real code serving no client
this project integrates with.

---

## Authentication

A static bearer token in `SCIM_BEARER_TOKEN`.

A SCIM client is a **service**, not a user. It has no session and no role, so
these routes bypass `require_role` entirely — which is exactly why the token
check is the first thing every one of them does.

- Its **own** credential, not reused from anywhere else. A SCIM client can
  create and deactivate accounts; it should be revocable on its own.
- Compared with `secrets.compare_digest`. String equality short-circuits on
  the first differing byte and leaks how much of a guess was right through
  response timing.
- **Blank rejects everything.** It never means "authentication disabled" —
  that is the failure mode that turns a config oversight into an open
  account-creation endpoint.
- A user JWT does not work here, and there is a test asserting it.

---

## Three behaviors worth understanding

### Create is idempotent on externalId

A client re-sending a create for a user it already provisioned gets **the
existing user back with 201**, not a 409.

Connectors re-sync — after a retry, a restart, or a full reconciliation.
Treating that as a conflict makes every re-sync look like a failure. A
*different* user claiming an existing `userName` is a genuine conflict and
does get 409 with `scimType: "uniqueness"`, which is the signal telling a
client to fetch the existing resource instead of retrying forever.

`externalId` is the client's stable identifier in its own directory. It is
what survives a rename, which `userName` and email do not.

### Deactivation, never deletion

`DELETE /Users/{id}` returns 204 and sets `active: false`. The row stays.

Deleting a user would orphan every approval they gave, every workflow they
started, and every audit row naming them — precisely the history you need
when investigating what a departed employee had access to. Returning 204
keeps well-behaved connectors happy while keeping the record.

Deactivation is enforced at the resource server too, not just in Keycloak: a
token issued minutes before deprovisioning stays cryptographically valid
until it expires, so the identity provider alone cannot revoke access
promptly.

### Unsupported PATCH paths are rejected, not ignored

A client that believes it disabled an account when nothing happened is a
security problem, not a compatibility one. Unknown paths return 400 with
`scimType: "invalidPath"`.

The same reasoning applies to filters: an unsupported filter returns
`invalidFilter` rather than being dropped, because ignoring it would return
the entire directory while looking like success.

---

## Interoperability details that cost real time

**Two PATCH shapes.** Okta sends targeted operations with an explicit `path`;
Keycloak sends untargeted ones whose `value` is an object of attributes. Both
are legal and both are implemented — supporting only one means the other
connector silently fails.

**Three spellings of false.** Clients send `false`, `"false"`, and `"False"`.
All three deactivate. Anything unrecognised raises rather than defaulting,
because guessing wrong leaves an account enabled that the directory believes
is disabled — the worst direction to be lenient in.

**Two role spellings.** Both `meridian-hr` and `hr` map to the HR role. A
connector's role catalog is configured by whoever set up the integration, and
insisting on one exact spelling is how everyone silently ends up with the
default role.

**Missing role means least privilege.** A create without `roles` gets
`employee`. An integration bug that drops the attribute should under-grant,
never over-grant.

**camelCase field names.** `userName`, `externalId`, `Resources`. That breaks
this codebase's snake_case convention, and it is the protocol's inconsistency
rather than ours — hiding it would break interoperability.

---

## Provisioned users and passwords

A provisioned user gets a random 32-byte password that is immediately
discarded. Nobody, including us, knows it.

The column is `NOT NULL` and a predictable placeholder would *be* a password.
These users authenticate through the identity provider, never against that
hash.

---

## Try it

```bash
# Set SCIM_BEARER_TOKEN in .env first:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

TOKEN=$(grep SCIM_BEARER_TOKEN .env | cut -d= -f2)

curl -X POST http://localhost:8000/scim/v2/Users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/scim+json" \
  -d '{
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "externalId": "kc-demo-1",
    "userName": "new.hire@cordant.io",
    "name": {"givenName": "New", "familyName": "Hire"},
    "emails": [{"value": "new.hire@cordant.io", "primary": true}],
    "roles": ["meridian-employee"],
    "active": true
  }'

# Re-run it — same id, still 201. That is the idempotency guarantee.

curl "http://localhost:8000/scim/v2/Users?filter=userName%20eq%20%22new.hire@cordant.io%22" \
  -H "Authorization: Bearer $TOKEN"
```

---

## What is verified

34 automated tests cover authentication (including that a user JWT is
refused), create idempotency, conflict handling, both PATCH shapes, every
spelling of false, role mapping, filter rejection, response envelopes, and
that deprovisioning actually removes access rather than setting a flag
nobody reads.

Not verified: a real Keycloak SCIM connector driving these endpoints
end to end. The contract is implemented to spec and tested against the
payload shapes Keycloak and Okta send, but no live connector has been
pointed at it.
