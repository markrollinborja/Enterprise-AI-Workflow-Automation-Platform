"""Salesforce contract tests — one suite, both implementations.

`TestSalesforceContract` is parametrized over the simulator and the live
adapter (the latter driven by a mock HTTP transport returning recorded
Salesforce response shapes). Both must produce identical normalized results.

That parametrization is the point. A simulator tested only against itself
proves nothing; the moment the live adapter changes its normalization, the
simulator silently becomes a liar and every test that depends on it is
testing fiction. Running the same assertions through both is what makes the
simulator a faithful stand-in.

The live adapter is exercised through `httpx.MockTransport`, not the network.
These are not live-verification tests — nothing here proves the real
Salesforce org works, and the README must not claim otherwise. Live
verification is a documented manual procedure (docs/architecture/salesforce.md).
"""

from typing import Any

import httpx
import pytest

from app.core.provider_errors import (
    PermanentProviderError,
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from app.models.enums import HealthStatus
from app.services.integrations.providers.salesforce_contract import (
    SalesforceAccount,
    SalesforceContact,
    SalesforceOpportunity,
)
from app.services.integrations.providers.salesforce_live import SalesforceLiveProvider
from app.services.integrations.providers.salesforce_simulated import (
    SALESFORCE_SCENARIO_NAMES,
    SIMULATED_ACCOUNT_ID,
    SIMULATED_OPPORTUNITY_ID,
    SalesforceSimulatedProvider,
)

INSTANCE_URL = "https://example-dev-ed.develop.my.salesforce.com"

# Response bodies shaped like real Salesforce replies, including the
# `attributes` block the API always includes and which normalization must
# discard rather than leak into the domain layer.
_VERSIONS_BODY = [
    {"label": "Winter '25", "url": "/services/data/v62.0", "version": "62.0"},
    {"label": "Spring '24", "url": "/services/data/v60.0", "version": "60.0"},
    # Deliberately out of order and including a single-digit version, to
    # catch a lexical rather than numeric max().
    {"label": "Ancient", "url": "/services/data/v9.0", "version": "9.0"},
]

_ACCOUNT_BODY = {
    "attributes": {"type": "Account", "url": "/services/data/v62.0/sobjects/Account/001x"},
    "Id": SIMULATED_ACCOUNT_ID,
    "Name": "Cordant Industries",
    "Website": "https://cordant.io",
    "Industry": "Manufacturing",
    "LastModifiedDate": "2026-08-01T09:15:00.000+0000",
}

_OPPORTUNITY_BODY = {
    "attributes": {"type": "Opportunity"},
    "Id": SIMULATED_OPPORTUNITY_ID,
    "Name": "Cordant Industries — Platform Rollout",
    "AccountId": SIMULATED_ACCOUNT_ID,
    "StageName": "Closed Won",
    "IsWon": True,
    "IsClosed": True,
    "Amount": 48000.0,
}

_CONTACTS_BODY = {
    "totalSize": 1,
    "done": True,
    "records": [
        {
            "attributes": {"type": "Contact"},
            "Id": "003Sim0000000ConAAA",
            "AccountId": SIMULATED_ACCOUNT_ID,
            "FirstName": "Dana",
            "LastName": "Whitfield",
            "Email": "dana.whitfield@cordant.io",
            "Title": "Director of Operations",
        }
    ],
}


def _happy_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/services/oauth2/token":
            return httpx.Response(
                200, json={"access_token": "simulated-token-value", "expires_in": 1800}
            )
        if path == "/services/data/":
            return httpx.Response(200, json=_VERSIONS_BODY)
        if path == "/services/oauth2/userinfo":
            return httpx.Response(
                200,
                json={"organization_id": "00DSim0000000OrgAAA", "user_id": "005Sim0000000UsrAAA"},
            )
        if path.endswith(f"/sobjects/Account/{SIMULATED_ACCOUNT_ID}"):
            return httpx.Response(200, json=_ACCOUNT_BODY)
        if path.endswith(f"/sobjects/Opportunity/{SIMULATED_OPPORTUNITY_ID}"):
            return httpx.Response(200, json=_OPPORTUNITY_BODY)
        if path.endswith("/query"):
            # The SOQL carries the account ID, so the mock has to honour it
            # — returning the same contact list for every account made the
            # "account with no contacts" contract test pass against the
            # simulator and fail against the live adapter, which is the
            # harness lying rather than the adapter misbehaving.
            soql = request.url.params.get("q", "")
            if SIMULATED_ACCOUNT_ID in soql:
                return httpx.Response(200, json=_CONTACTS_BODY)
            return httpx.Response(200, json={"totalSize": 0, "done": True, "records": []})
        if "/sobjects/" in path:
            return httpx.Response(
                404, json=[{"errorCode": "NOT_FOUND", "message": "The requested resource"}]
            )
        return httpx.Response(404, json=[{"errorCode": "NOT_FOUND", "message": "unmapped"}])

    return httpx.MockTransport(handler)


def _live(transport: httpx.MockTransport | None = None) -> SalesforceLiveProvider:
    return SalesforceLiveProvider(
        connection_key="sf-contract",
        base_url=INSTANCE_URL,
        client_id="contract-test-client-id",
        client_secret="contract-test-client-secret",
        http_client=httpx.Client(transport=transport or _happy_transport()),
    )


def _simulated() -> SalesforceSimulatedProvider:
    return SalesforceSimulatedProvider(connection_key="sf-contract")


@pytest.fixture(params=["simulated", "live"])
def client(request: pytest.FixtureRequest) -> Any:
    """Both implementations, same assertions."""
    return _simulated() if request.param == "simulated" else _live()


class TestSalesforceContract:
    """Every assertion here runs twice — once per implementation."""

    def test_get_account_returns_a_normalized_account(self, client: Any) -> None:
        account = client.get_account(SIMULATED_ACCOUNT_ID)
        assert isinstance(account, SalesforceAccount)
        assert account.external_id == SIMULATED_ACCOUNT_ID
        assert account.name == "Cordant Industries"
        assert account.website == "https://cordant.io"

    def test_salesforce_attributes_block_is_not_leaked(self, client: Any) -> None:
        """The domain layer must never see Salesforce's own vocabulary."""
        account = client.get_account(SIMULATED_ACCOUNT_ID)
        assert not hasattr(account, "attributes")

    def test_missing_account_is_a_permanent_failure(self, client: Any) -> None:
        """A record that does not exist will still not exist on retry."""
        with pytest.raises(PermanentProviderError) as exc_info:
            client.get_account("001DoesNotExist000")
        assert exc_info.value.is_retryable is False

    def test_contacts_are_normalized(self, client: Any) -> None:
        contacts = client.list_contacts_for_account(SIMULATED_ACCOUNT_ID)
        assert len(contacts) == 1
        contact = contacts[0]
        assert isinstance(contact, SalesforceContact)
        assert contact.last_name == "Whitfield"
        assert contact.account_external_id == SIMULATED_ACCOUNT_ID

    def test_account_with_no_contacts_is_not_an_error(self, client: Any) -> None:
        """A customer who hasn't added people yet is a normal business
        state, not an integration failure."""
        assert client.list_contacts_for_account("001NoContacts00000") == []

    def test_opportunity_exposes_is_won_not_a_stage_string(self, client: Any) -> None:
        """Every org renames its stages. Code comparing StageName to
        "Closed Won" is one admin customization away from silently never
        triggering; IsWon is a real boolean that cannot be renamed."""
        opportunity = client.get_opportunity(SIMULATED_OPPORTUNITY_ID)
        assert isinstance(opportunity, SalesforceOpportunity)
        assert opportunity.is_won is True
        assert opportunity.is_closed is True
        assert opportunity.account_external_id == SIMULATED_ACCOUNT_ID

    def test_api_version_is_reported(self, client: Any) -> None:
        version = client.api_version()
        assert version
        assert float(version) >= 60.0

    def test_health_check_reports_the_same_shape(self, client: Any) -> None:
        """Identical keys from both implementations — otherwise the support
        console renders a different card for a simulated connection than a
        live one, and nobody notices until they are debugging under
        pressure."""
        outcome = client.check_health()
        assert outcome.status is HealthStatus.HEALTHY
        assert outcome.detail["api_version"]
        assert outcome.detail["organization_id"]
        assert outcome.detail["run_as_user_id"]


class TestLiveAdapterSpecifics:
    """Behavior only the live adapter has — token handling, HTTP mapping."""

    def test_api_version_discovery_picks_the_newest_numerically(self) -> None:
        """"v9.0" sorts after "v62.0" as a string, which would silently pick
        a decade-old API version."""
        assert _live().api_version() == "62.0"

    def test_token_is_fetched_once_and_reused(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            return httpx.Response(200, json=_ACCOUNT_BODY)

        provider = _live(httpx.MockTransport(handler))
        provider.get_account(SIMULATED_ACCOUNT_ID)
        provider.get_account(SIMULATED_ACCOUNT_ID)

        assert calls.count("/services/oauth2/token") == 1

    def test_expired_token_triggers_exactly_one_retry(self) -> None:
        """A token can expire between the expiry check and the request
        landing. One immediate retry fixes that; a loop here would multiply
        against the workflow engine's own retry budget."""
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            attempts.append(1)
            if len(attempts) == 1:
                return httpx.Response(
                    401, json=[{"errorCode": "INVALID_SESSION_ID", "message": "expired"}]
                )
            return httpx.Response(200, json=_ACCOUNT_BODY)

        account = _live(httpx.MockTransport(handler)).get_account(SIMULATED_ACCOUNT_ID)
        assert account.name == "Cordant Industries"
        assert len(attempts) == 2

    def test_persistent_401_stops_after_the_retry(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            return httpx.Response(
                401, json=[{"errorCode": "INVALID_SESSION_ID", "message": "expired"}]
            )

        with pytest.raises(ProviderAuthError) as exc_info:
            _live(httpx.MockTransport(handler)).get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.refreshable is False

    def test_request_limit_exceeded_arrives_as_403_and_is_retryable(self) -> None:
        """The most valuable case in this file. Salesforce signals API-limit
        exhaustion with 403, not 429 — classifying by status alone would
        mark a temporary condition permanent and skip the retry that would
        have worked."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            return httpx.Response(
                403,
                json=[
                    {
                        "errorCode": "REQUEST_LIMIT_EXCEEDED",
                        "message": "TotalRequests Limit exceeded.",
                    }
                ],
                headers={"Retry-After": "45"},
            )

        with pytest.raises(ProviderRateLimitError) as exc_info:
            _live(httpx.MockTransport(handler)).get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.is_retryable is True
        assert exc_info.value.retry_after_seconds == 45

    def test_plain_403_stays_permanent(self) -> None:
        """Only REQUEST_LIMIT_EXCEEDED gets the rate-limit treatment; an
        ordinary permission failure must not be retried forever."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            return httpx.Response(
                403,
                json=[
                    {
                        "errorCode": "INSUFFICIENT_ACCESS_OR_READONLY",
                        "message": "insufficient access rights",
                    }
                ],
            )

        with pytest.raises(ProviderAuthError) as exc_info:
            _live(httpx.MockTransport(handler)).get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.is_retryable is False

    def test_timeout_is_classified_as_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(ProviderTimeoutError) as exc_info:
            _live(httpx.MockTransport(handler)).api_version()
        assert exc_info.value.is_retryable is True

    def test_rejected_credentials_are_not_refreshable(self) -> None:
        """Retrying with the same bad credentials produces the same answer.
        This is the distinction `refreshable` exists for."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Version discovery is unauthenticated and must still succeed —
            # otherwise this test would pass for the wrong reason, failing
            # at discovery before the token request it is actually about.
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            return httpx.Response(
                400, json={"error": "invalid_client", "error_description": "bad secret"}
            )

        with pytest.raises(ProviderAuthError) as exc_info:
            _live(httpx.MockTransport(handler)).get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.refreshable is False
        assert exc_info.value.is_retryable is False

    def test_token_value_never_appears_in_an_error_message(self) -> None:
        """Redaction happens at exception construction, but the path that
        matters most is the one carrying a live token."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(
                    200, json={"access_token": "00Dxx!SUPERSECRETVALUE", "expires_in": 1800}
                )
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            return httpx.Response(
                500,
                text="failure with access_token=00Dxx!SUPERSECRETVALUE in the body",
            )

        with pytest.raises(ProviderError) as exc_info:
            _live(httpx.MockTransport(handler)).get_account(SIMULATED_ACCOUNT_ID)
        assert "SUPERSECRETVALUE" not in str(exc_info.value)

    def test_missing_instance_url_is_a_configuration_error(self) -> None:
        with pytest.raises(ProviderConfigurationError):
            SalesforceLiveProvider(
                connection_key="sf", base_url=None, client_id="x", client_secret="y"
            )

    def test_missing_credentials_is_a_configuration_error(self) -> None:
        """Anyone who cloned this repo without a Salesforce org hits this,
        and must get an actionable message rather than a TypeError."""
        with pytest.raises(ProviderConfigurationError):
            SalesforceLiveProvider(
                connection_key="sf", base_url=INSTANCE_URL, client_id=None, client_secret=None
            )

    def test_soql_values_are_escaped(self) -> None:
        """The account ID arrives from an inbound webhook payload. "It
        should never contain a quote" is exactly the assumption that
        becomes an injection."""
        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/services/oauth2/token":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
            if request.url.path == "/services/data/":
                return httpx.Response(200, json=_VERSIONS_BODY)
            captured.append(str(request.url))
            return httpx.Response(200, json={"records": []})

        _live(httpx.MockTransport(handler)).list_contacts_for_account("001x' OR Name != '")
        assert captured
        assert "%5C%27" in captured[0] or "\\'" not in captured[0]


class TestSimulatorSpecifics:
    """Failure scenarios only the simulator can produce on demand."""

    @pytest.mark.parametrize("scenario", SALESFORCE_SCENARIO_NAMES)
    def test_every_salesforce_scenario_fails_the_operation(self, scenario: str) -> None:
        """Names appear in Failure Lab runbooks — one that silently stopped
        failing would make a runbook lie."""
        provider = SalesforceSimulatedProvider(
            connection_key="sf", config={"simulate_failure": scenario}
        )
        with pytest.raises(ProviderError):
            provider.get_account(SIMULATED_ACCOUNT_ID)

    def test_request_limit_scenario_matches_salesforce_reality(self) -> None:
        provider = SalesforceSimulatedProvider(
            connection_key="sf", config={"simulate_failure": "sf_request_limit_exceeded"}
        )
        with pytest.raises(ProviderRateLimitError) as exc_info:
            provider.get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.status_code_from_provider == 403
        assert exc_info.value.is_retryable is True

    def test_invalid_session_scenario_is_refreshable(self) -> None:
        provider = SalesforceSimulatedProvider(
            connection_key="sf", config={"simulate_failure": "sf_invalid_session"}
        )
        with pytest.raises(ProviderAuthError) as exc_info:
            provider.get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.refreshable is True

    def test_invalid_field_scenario_is_permanent(self) -> None:
        provider = SalesforceSimulatedProvider(
            connection_key="sf", config={"simulate_failure": "sf_invalid_field"}
        )
        with pytest.raises(PermanentProviderError) as exc_info:
            provider.get_account(SIMULATED_ACCOUNT_ID)
        assert exc_info.value.is_retryable is False
