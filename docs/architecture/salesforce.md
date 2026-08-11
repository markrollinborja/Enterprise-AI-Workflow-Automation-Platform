# Salesforce Integration

**Status:** adapter and simulator implemented (Phase 2). Live verification is a
documented manual procedure — see [Live verification](#live-verification). The
README's live-versus-simulated disclosure is generated from
`registry.live_adapter_providers()`, not maintained by hand.

---

## What this integration does

Consumes customer data from Salesforce to drive organization onboarding:

- read an Account, its Contacts, and an Opportunity
- detect a won deal and start the onboarding transaction
- map Salesforce IDs to local records through `external_identities`

**It is read-only, deliberately.** Nothing writes back to Salesforce. Write
access to a CRM is where an integration bug stops being embarrassing and starts
being expensive, and nothing in the demonstration needs it. This is a scope
decision, not an oversight.

---

## Why client-credentials OAuth

Salesforce offers several server-to-server options:

| Flow | Why not / why |
|---|---|
| Username-password | Deprecated, disabled by default in new orgs |
| JWT bearer | Needs a certificate uploaded to the app and a signed assertion per request — more moving parts to set up and to explain |
| **Client credentials** | **Chosen.** Standard OAuth 2.0 grant, needs only client ID/secret plus a designated Run-As user, and is genuinely what a service integration should use |

Setup ceremony matters here: this is a portfolio project someone else has to be
able to run from a README.

---

## API version is discovered, not pinned

The adapter calls `/services/data/` (unauthenticated) and uses the newest
version the org reports.

Salesforce ships three releases a year. Any `v62.0` hardcoded in source is
stale within months and fails as a 404 on a URL that looks correct — one of the
more annoying things to debug. Discovery costs one cached call per process.

The version is recorded on every health check, because "which API version
produced this data" is the first question when a field starts arriving empty
after a Salesforce release.

---

## Error mapping

Salesforce's error semantics do not line up with HTTP status codes, and the
adapter compensates:

| Salesforce response | Mapped to | Retryable | Why |
|---|---|---|---|
| `403 REQUEST_LIMIT_EXCEEDED` | `ProviderRateLimitError` | **Yes** | Salesforce signals API-limit exhaustion with **403, not 429**. Classifying by status alone marks a purely temporary condition permanent and skips the retry that would have worked. |
| `403` anything else | `ProviderAuthError` (not refreshable) | No | A genuine permission problem needs a human |
| `401 INVALID_SESSION_ID` | one immediate retry, then `ProviderAuthError` | No after retry | A token can expire between the expiry check and the request landing |
| `400 invalid_client` on token | `ProviderAuthError` (not refreshable) | No | Retrying with the same bad credentials produces the same answer |
| `404 NOT_FOUND` / `ENTITY_IS_DELETED` | `PermanentProviderError` | No | Common with at-least-once delivery; the record will still be gone on retry |
| Timeout | `ProviderTimeoutError` | Yes | Request may have succeeded upstream — treat as unknown outcome, not failure |

The `403 REQUEST_LIMIT_EXCEEDED` case is the one worth remembering. It is
reproduced by the simulator (`simulate_failure: sf_request_limit_exceeded`) so
the special case is actually tested rather than merely written.

---

## Token handling

- Requested on demand, cached in memory with a 60-second expiry margin
- **Never persisted.** A credential written to a database is a credential in
  every backup, and the only thing persistence buys is skipping a sub-second
  token call after a restart
- Guarded by a lock, because the worker polls on a loop while the API serves
  concurrent requests and both can reach for a token at once
- One immediate retry on a 401, and no more — general retry belongs to the
  workflow engine, which already has backoff and attempt limits

---

## Simulator

`SalesforceSimulatedProvider` satisfies the same contract and reproduces
Salesforce-specific failures on demand. Set on the connection's `config`:

| `simulate_failure` | Reproduces |
|---|---|
| `sf_request_limit_exceeded` | 403 + `REQUEST_LIMIT_EXCEEDED`, retryable |
| `sf_invalid_session` | 401 + `INVALID_SESSION_ID`, refreshable |
| `sf_invalid_field` | 400 + `INVALID_FIELD`, permanent |
| `sf_insufficient_access` | 403 + `INSUFFICIENT_ACCESS_OR_READONLY`, permanent |
| `sf_record_deleted` | 404 + `ENTITY_IS_DELETED`, permanent |

Plus the generic scenarios from `SimulatedProvider` (timeout, unreachable,
rate limited, expired token, revoked grant, missing permission, misconfigured).

Both implementations run through the same test suite
(`tests/test_salesforce_contract.py`), parametrized over live and simulated.
A simulator tested only against itself proves nothing.

---

## Org setup

1. **Sign up** for a free Developer Edition org: https://developer.salesforce.com/signup
   Your *username* looks like an email but need not be one you own; your
   *email* must be real. The username gets a generated suffix — find it under
   Setup → Users.

2. **Create an External Client App**: Setup → Quick Find → *External Client App
   Manager* → New.
   - Name: `Meridian Flow Integration`
   - Distribution State: Local
   - Expand **API (Enable OAuth Settings)** → tick **Enable OAuth**
   - Callback URL: `http://localhost:8000/integrations/salesforce/oauth/callback`
   - Scopes: **Manage user data via APIs (api)**, **Perform requests at any
     time (refresh_token, offline_access)**

3. **Enable client credentials**: open the app → **Policies** → OAuth Policies →
   tick **Enable Client Credentials Flow** → set **Run As** to your Salesforce
   *username* (not your email; the save fails with "Enter a valid execution
   user" otherwise).

4. **Collect credentials**: app → Settings → OAuth → *Consumer Key and Secret*.
   Instance URL comes from Setup → **My Domain** → "Current My Domain URL".

5. **Configure `.env`** — note the domain suffix:

   ```
   SALESFORCE_INSTANCE_URL=https://your-org.develop.my.salesforce.com
   SALESFORCE_CLIENT_ID=...
   SALESFORCE_CLIENT_SECRET=...
   ```

   `.my.salesforce.com`, **not** the `.lightning.force.com` URL in your browser.
   The Lightning domain returns redirects rather than a clean error.

Allow ~10 minutes after saving the app before the credentials work — Salesforce
propagates them asynchronously.

---

## Live verification

Nothing in the automated suite touches a real Salesforce org — the contract
tests drive the live adapter through a mock HTTP transport. Live verification is
manual, and until it has been run and recorded, this integration is **simulated**.

From `backend/`, with `.env` populated:

```bash
python -c "
from app.core.config import get_settings
from app.services.integrations.providers.salesforce_live import SalesforceLiveProvider
s = get_settings()
p = SalesforceLiveProvider(
    connection_key='sf-dev',
    base_url=s.salesforce_instance_url,
    client_id=s.salesforce_client_id,
    client_secret=s.salesforce_client_secret,
)
outcome = p.check_health()
print(outcome.status, outcome.detail)
"
```

Expected: `HealthStatus.HEALTHY` plus a dict containing `api_version`,
`organization_id`, and `run_as_user_id`.

**Common failures**

| Symptom | Cause |
|---|---|
| `invalid_client` | Wrong Consumer Key/Secret, or the app has not finished propagating (wait 10 min) |
| `invalid_grant` / `no such user` | Run-As user not set, or set to an email instead of a username |
| Redirect / HTML response | `SALESFORCE_INSTANCE_URL` points at `.lightning.force.com` |
| `ProviderConfigurationError` | One or more of the three variables is blank |

When it passes, record the date and result in
`docs/portfolio/project-evidence.md` under live-verified integrations. An
integration is only "live-verified" if someone actually ran it against the real
provider and wrote down what happened.
