"""Live Salesforce adapter — OAuth 2.0 client credentials + REST API.

**Why client credentials.** Salesforce offers several server-to-server flows.
JWT bearer needs a certificate uploaded to the connected app and a signed
assertion per request; username-password is deprecated and disabled by
default in new orgs. Client credentials is a standard, current OAuth 2.0
grant, needs only a client ID/secret plus a designated Run-As user, and is
genuinely what a service integration should use. It is also the least
ceremony to reproduce, which matters for a project someone else has to be
able to set up from a README.

**API version is discovered, not hardcoded.** Salesforce ships three releases
a year. Any `v62.0` pinned in source is stale within months and fails in the
least helpful way — a 404 on a URL that looks correct. `/services/data/` is
unauthenticated and returns every version the org supports, so the adapter
asks once per process and uses the newest.

**Token caching.** Client credentials tokens are short-lived and Salesforce
does not issue a refresh token for this grant — you simply request another.
The token is held in memory with an expiry margin, never persisted: a
credential written to a database is a credential in every backup, and the
only thing that buys is skipping a sub-second token call after a restart.
"""

import logging
import threading
import time
from typing import Any, NoReturn
from urllib.parse import quote

import httpx

from app.core.provider_errors import (
    PermanentProviderError,
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TransientProviderError,
    classify_status,
)
from app.models.enums import ProviderMode, ProviderType
from app.services.integrations.providers.base import Provider
from app.services.integrations.providers.salesforce_contract import (
    SalesforceAccount,
    SalesforceContact,
    SalesforceOpportunity,
)

logger = logging.getLogger(__name__)

# Requested slightly before the token actually expires. A token that is
# valid when checked and expired when the request lands is a race that
# produces a confusing intermittent 401; 60s of margin removes it.
TOKEN_EXPIRY_MARGIN_SECONDS = 60

# Salesforce's own default session length for this grant is long, but the
# token response carries no `expires_in` for client credentials in some org
# configurations. When it is absent, assume a conservative lifetime rather
# than treating the token as valid forever.
DEFAULT_TOKEN_LIFETIME_SECONDS = 1800

DEFAULT_TIMEOUT_SECONDS = 20.0


class SalesforceLiveProvider(Provider):
    """Talks to a real Salesforce org."""

    provider_type = ProviderType.SALESFORCE
    mode = ProviderMode.LIVE

    def __init__(
        self,
        *,
        connection_key: str,
        base_url: str | None = None,
        config: dict[str, Any] | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(connection_key=connection_key, base_url=base_url, config=config)

        if not base_url:
            raise ProviderConfigurationError(
                "Salesforce connection has no instance URL configured",
                provider=ProviderType.SALESFORCE.value,
                operation="configure",
            )
        if not client_id or not client_secret:
            raise ProviderConfigurationError(
                "Salesforce connection is missing client credentials",
                provider=ProviderType.SALESFORCE.value,
                operation="configure",
            )

        self._instance_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = http_client or httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)

        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._api_version: str | None = None
        # The worker polls on a loop and the API serves concurrent requests;
        # both can reach for a token at once. Without this, a burst of
        # concurrent calls after expiry each fetch their own token — wasteful
        # and a good way to meet Salesforce's login rate limit.
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- auth

    def _fetch_token(self) -> None:
        """Request a fresh access token. Caller must hold the lock."""
        try:
            response = self._client.post(
                f"{self._instance_url}/services/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Timed out requesting Salesforce token: {exc}",
                provider=ProviderType.SALESFORCE.value,
                operation="oauth_token",
            ) from exc
        except httpx.HTTPError as exc:
            raise TransientProviderError(
                f"Network error requesting Salesforce token: {exc}",
                provider=ProviderType.SALESFORCE.value,
                operation="oauth_token",
            ) from exc

        if response.status_code != 200:
            # A failed *token* request is never refreshable — retrying with
            # the same credentials produces the same answer. This is the
            # distinction ProviderAuthError.refreshable exists for: an
            # expired API token can be fixed by fetching a new one, but a
            # rejected credential cannot fix itself.
            raise ProviderAuthError(
                f"Salesforce token request failed ({response.status_code}): {response.text}",
                refreshable=False,
                provider=ProviderType.SALESFORCE.value,
                operation="oauth_token",
                status_code_from_provider=response.status_code,
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ProviderAuthError(
                "Salesforce token response contained no access_token",
                refreshable=False,
                provider=ProviderType.SALESFORCE.value,
                operation="oauth_token",
            )

        lifetime = int(payload.get("expires_in", DEFAULT_TOKEN_LIFETIME_SECONDS))
        self._access_token = token
        self._token_expires_at = time.monotonic() + lifetime - TOKEN_EXPIRY_MARGIN_SECONDS

        # Never log the token, and never log the raw response — Salesforce
        # echoes the instance URL and id here, and a future SDK change
        # could add more. Only the fact and the lifetime.
        logger.info(
            "Acquired Salesforce access token",
            extra={
                "provider": ProviderType.SALESFORCE.value,
                "connection_key": self.connection_key,
                "token_lifetime_seconds": lifetime,
            },
        )

    def _token(self) -> str:
        with self._lock:
            if self._access_token is None or time.monotonic() >= self._token_expires_at:
                self._fetch_token()
            token = self._access_token
            if token is None:  # pragma: no cover - _fetch_token raises instead
                raise ProviderAuthError(
                    "Salesforce token unavailable after acquisition",
                    refreshable=False,
                    provider=ProviderType.SALESFORCE.value,
                    operation="oauth_token",
                )
            return token

    def _invalidate_token(self) -> None:
        with self._lock:
            self._access_token = None
            self._token_expires_at = 0.0

    # ------------------------------------------------------------- version

    def api_version(self) -> str:
        """Newest API version this org supports, discovered once per process."""
        if self._api_version is not None:
            return self._api_version

        try:
            response = self._client.get(f"{self._instance_url}/services/data/")
        except httpx.TimeoutException as exc:
            # Caught before the general HTTPError branch: a timeout is a
            # timeout on every code path, and collapsing it into a generic
            # transient error here would make version discovery the one
            # place where "the provider went quiet" reads differently in
            # the support console.
            raise ProviderTimeoutError(
                f"Timed out discovering Salesforce API versions: {exc}",
                provider=ProviderType.SALESFORCE.value,
                operation="discover_api_version",
            ) from exc
        except httpx.HTTPError as exc:
            raise TransientProviderError(
                f"Could not discover Salesforce API versions: {exc}",
                provider=ProviderType.SALESFORCE.value,
                operation="discover_api_version",
            ) from exc

        if response.status_code != 200:
            raise classify_status(response.status_code)(
                f"Salesforce version discovery failed ({response.status_code})",
                provider=ProviderType.SALESFORCE.value,
                operation="discover_api_version",
                status_code_from_provider=response.status_code,
            )

        versions = response.json()
        if not versions:
            raise PermanentProviderError(
                "Salesforce reported no supported API versions",
                provider=ProviderType.SALESFORCE.value,
                operation="discover_api_version",
            )

        # Sorted numerically, not lexically: "v9.0" sorts after "v62.0" as
        # a string, which would pick a decade-old version.
        newest = max(versions, key=lambda v: float(str(v["version"])))
        self._api_version = str(newest["version"])
        return self._api_version

    # ---------------------------------------------------------------- http

    def _get(self, path: str, *, operation: str, retry_on_auth: bool = True) -> dict[str, Any]:
        """Authenticated GET against the REST API, with one auth retry.

        The single retry exists because a token can expire between the
        expiry check and the request landing — a genuinely transient
        condition that one immediate retry fixes. It is deliberately not a
        general retry loop: that belongs to the workflow engine, which
        already has backoff and attempt limits, and duplicating it here
        would multiply the two together.
        """
        url = f"{self._instance_url}{path}"
        try:
            response = self._client.get(
                url, headers={"Authorization": f"Bearer {self._token()}"}
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Salesforce request timed out: {exc}",
                provider=ProviderType.SALESFORCE.value,
                operation=operation,
            ) from exc
        except httpx.HTTPError as exc:
            raise TransientProviderError(
                f"Salesforce request failed: {exc}",
                provider=ProviderType.SALESFORCE.value,
                operation=operation,
            ) from exc

        if response.status_code == 401 and retry_on_auth:
            self._invalidate_token()
            return self._get(path, operation=operation, retry_on_auth=False)

        if response.status_code == 200:
            data: dict[str, Any] = response.json()
            return data

        self._raise_for_response(response, operation=operation)

    def _raise_for_response(self, response: httpx.Response, *, operation: str) -> NoReturn:
        """Translate a Salesforce error response into our taxonomy."""
        detail = self._error_detail(response)

        if response.status_code == 401:
            raise ProviderAuthError(
                f"Salesforce rejected the session: {detail}",
                # Reached only after the single retry above already failed,
                # so a further refresh will not help.
                refreshable=False,
                provider=ProviderType.SALESFORCE.value,
                operation=operation,
                status_code_from_provider=401,
            )

        if response.status_code == 403 and "REQUEST_LIMIT_EXCEEDED" in detail:
            # Salesforce signals API limit exhaustion with 403 and this
            # error code, not 429. Classifying it by status alone would
            # mark a purely temporary condition permanent and skip the
            # retry that would have succeeded.
            raise ProviderRateLimitError(
                f"Salesforce API request limit exceeded: {detail}",
                provider=ProviderType.SALESFORCE.value,
                operation=operation,
                status_code_from_provider=403,
                retry_after_seconds=self._retry_after(response),
            )

        if response.status_code == 429:
            raise ProviderRateLimitError(
                f"Salesforce rate limited the request: {detail}",
                provider=ProviderType.SALESFORCE.value,
                operation=operation,
                status_code_from_provider=429,
                retry_after_seconds=self._retry_after(response),
            )

        raise classify_status(response.status_code)(
            f"Salesforce request failed ({response.status_code}): {detail}",
            provider=ProviderType.SALESFORCE.value,
            operation=operation,
            status_code_from_provider=response.status_code,
        )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Salesforce errors are a JSON array of {errorCode, message}.

        Falls back to raw text, because an HTML error page from a proxy in
        front of the org is exactly the case where you most want to see
        what actually came back.
        """
        try:
            body = response.json()
        except ValueError:
            return response.text[:300]

        if isinstance(body, list) and body:
            first = body[0]
            if isinstance(first, dict):
                return f"{first.get('errorCode', 'UNKNOWN')}: {first.get('message', '')}"
        return str(body)[:300]

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            # Retry-After may be an HTTP date rather than seconds. Rather
            # than parse it, fall back to the engine's own backoff — a
            # wrong number here would be worse than no number.
            return None

    # ------------------------------------------------------------ contract

    def get_account(self, external_id: str) -> SalesforceAccount:
        version = self.api_version()
        data = self._get(
            f"/services/data/v{version}/sobjects/Account/{external_id}",
            operation="get_account",
        )
        return SalesforceAccount(
            external_id=str(data["Id"]),
            name=str(data.get("Name", "")),
            website=data.get("Website"),
            industry=data.get("Industry"),
            last_modified=data.get("LastModifiedDate"),
        )

    def list_contacts_for_account(self, account_external_id: str) -> list[SalesforceContact]:
        version = self.api_version()
        # SOQL rather than the relationship endpoint: it returns exactly
        # the fields needed in one round trip, and the query is visible
        # here rather than implied by an endpoint's default field set.
        soql = (
            "SELECT Id, AccountId, FirstName, LastName, Email, Title "
            f"FROM Contact WHERE AccountId = '{_escape_soql(account_external_id)}'"
        )
        data = self._get(
            f"/services/data/v{version}/query?q={_url_encode(soql)}",
            operation="list_contacts",
        )
        return [
            SalesforceContact(
                external_id=str(record["Id"]),
                account_external_id=str(record.get("AccountId") or account_external_id),
                first_name=record.get("FirstName"),
                last_name=str(record.get("LastName", "")),
                email=record.get("Email"),
                title=record.get("Title"),
            )
            for record in data.get("records", [])
        ]

    def get_opportunity(self, external_id: str) -> SalesforceOpportunity:
        version = self.api_version()
        data = self._get(
            f"/services/data/v{version}/sobjects/Opportunity/{external_id}",
            operation="get_opportunity",
        )
        return SalesforceOpportunity(
            external_id=str(data["Id"]),
            name=str(data.get("Name", "")),
            account_external_id=data.get("AccountId"),
            stage_name=str(data.get("StageName", "")),
            # IsWon, not StageName == "Closed Won": every org renames its
            # stages, and IsWon is a real boolean that cannot be renamed.
            is_won=bool(data.get("IsWon", False)),
            is_closed=bool(data.get("IsClosed", False)),
            amount=data.get("Amount"),
        )

    # -------------------------------------------------------------- health

    def _perform_health_check(self) -> dict[str, Any]:
        """Cheapest call that proves credentials actually work.

        `/services/oauth2/userinfo` is the right choice: it requires a valid
        token, so it exercises the whole credential path, and it returns
        almost nothing. A query against a real object would also work but
        consumes API quota that a check running every minute should not.
        """
        version = self.api_version()
        info = self._get("/services/oauth2/userinfo", operation="health_check")
        return {
            "api_version": version,
            "organization_id": info.get("organization_id"),
            # Deliberately not the email or the user's name — a health
            # payload is rendered in the support console and does not need
            # to carry personal data to prove the connection works.
            "run_as_user_id": info.get("user_id"),
        }


def _escape_soql(value: str) -> str:
    """Escape a value for inclusion in a SOQL string literal.

    Salesforce IDs are alphanumeric, so this should never have anything to
    do — but the value arrives from an inbound webhook payload, and "it
    should never contain a quote" is exactly the assumption that turns into
    an injection. Escaping unconditionally costs nothing.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _url_encode(value: str) -> str:
    return quote(value, safe="")
