"""Salesforce simulator — satisfies the same contract as the live adapter.

Inherits the generic failure scenarios from SimulatedProvider (expired token,
rate limit, missing permission, timeout, ...) and adds the ones that are
specifically Salesforce-shaped:

- `REQUEST_LIMIT_EXCEEDED` arriving as **403, not 429**. This is the single
  most valuable behavior in the file. Salesforce signals API-limit exhaustion
  with a 403, so any code that classifies purely by HTTP status marks a
  temporary condition permanent and never retries. The live adapter special-
  cases it; the simulator reproduces it so that special case is actually
  tested rather than merely written.
- `INVALID_SESSION_ID`, the expired-session error, which is refreshable.
- `INVALID_FIELD`, a field-mapping mistake, which is permanent — no amount of
  retrying fixes a query for a column that does not exist.
- `NOT_FOUND` for a record that has been deleted between the event being
  emitted and us reading it, which is common with at-least-once delivery.

Holds a small in-memory dataset so the contract tests exercise real data
shapes rather than empty structures. The fictional company matches the demo
data used elsewhere in the project (Cordant Industries).
"""

from typing import Any

from app.core.provider_errors import (
    PermanentProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
)
from app.models.enums import ProviderType
from app.services.integrations.providers.salesforce_contract import (
    SalesforceAccount,
    SalesforceContact,
    SalesforceOpportunity,
)
from app.services.integrations.providers.simulated import SimulatedProvider

# The API version the simulator claims. A fixed, obviously-plausible value:
# the simulator is not pretending to discover anything, and a test asserting
# on version behavior should be testing the live adapter's discovery logic.
SIMULATED_API_VERSION = "62.0"

# Salesforce IDs are 15 or 18 characters with a 3-character object prefix —
# 001 for Account, 003 for Contact, 006 for Opportunity. Using realistic
# shapes means code that (wrongly) infers object type from an ID prefix
# behaves the same against the simulator as it would against a real org.
_ACCOUNT_ID = "001Sim0000000AccAAA"
_CONTACT_ID = "003Sim0000000ConAAA"
_OPPORTUNITY_ID = "006Sim0000000OppAAA"

_ACCOUNTS: dict[str, SalesforceAccount] = {
    _ACCOUNT_ID: SalesforceAccount(
        external_id=_ACCOUNT_ID,
        name="Cordant Industries",
        website="https://cordant.io",
        industry="Manufacturing",
        last_modified="2026-08-01T09:15:00.000+0000",
    )
}

_CONTACTS: dict[str, list[SalesforceContact]] = {
    _ACCOUNT_ID: [
        SalesforceContact(
            external_id=_CONTACT_ID,
            account_external_id=_ACCOUNT_ID,
            first_name="Dana",
            last_name="Whitfield",
            email="dana.whitfield@cordant.io",
            title="Director of Operations",
        )
    ]
}

_OPPORTUNITIES: dict[str, SalesforceOpportunity] = {
    _OPPORTUNITY_ID: SalesforceOpportunity(
        external_id=_OPPORTUNITY_ID,
        name="Cordant Industries — Platform Rollout",
        account_external_id=_ACCOUNT_ID,
        stage_name="Closed Won",
        is_won=True,
        is_closed=True,
        amount=48000.0,
    )
}


class SalesforceSimulatedProvider(SimulatedProvider):
    """Stands in for a Salesforce org, including its specific error shapes."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("provider_type", ProviderType.SALESFORCE)
        super().__init__(**kwargs)

    # ------------------------------------------------------------ contract

    def api_version(self) -> str:
        return SIMULATED_API_VERSION

    def get_account(self, external_id: str) -> SalesforceAccount:
        self._maybe_fail("get_account")
        account = _ACCOUNTS.get(external_id)
        if account is None:
            raise PermanentProviderError(
                f"NOT_FOUND: The requested resource does not exist ({external_id})",
                provider=ProviderType.SALESFORCE.value,
                operation="get_account",
                status_code_from_provider=404,
            )
        return account

    def list_contacts_for_account(self, account_external_id: str) -> list[SalesforceContact]:
        self._maybe_fail("list_contacts")
        # Empty list, not an error: an account with no contacts is a normal
        # business state, and treating it as a failure would break onboarding
        # for every customer who hasn't added people yet.
        return list(_CONTACTS.get(account_external_id, []))

    def get_opportunity(self, external_id: str) -> SalesforceOpportunity:
        self._maybe_fail("get_opportunity")
        opportunity = _OPPORTUNITIES.get(external_id)
        if opportunity is None:
            raise PermanentProviderError(
                f"NOT_FOUND: The requested resource does not exist ({external_id})",
                provider=ProviderType.SALESFORCE.value,
                operation="get_opportunity",
                status_code_from_provider=404,
            )
        return opportunity

    # ------------------------------------------------------------ failures

    def _maybe_fail(self, operation: str) -> None:
        """Apply the configured Salesforce-specific failure, if any.

        Read from the same `simulate_failure` config key the generic
        simulator uses, so one mechanism drives every scenario across every
        provider and a Failure Lab runbook reads the same way regardless of
        which integration it is exercising.
        """
        scenario = str(self.config.get("simulate_failure", "none")).lower()
        handler = _SALESFORCE_SCENARIOS.get(scenario)
        if handler is not None:
            handler(operation)

    def _perform_health_check(self) -> dict[str, Any]:
        """Mirrors the live adapter's health payload shape.

        Same keys, simulated values. If these diverged, the support console
        would render a different card for a simulated connection than a live
        one, and the difference would be invisible until someone was
        debugging under pressure.
        """
        super()._perform_health_check()
        return {
            "simulated": True,
            "api_version": SIMULATED_API_VERSION,
            "organization_id": "00DSim0000000OrgAAA",
            "run_as_user_id": "005Sim0000000UsrAAA",
        }


def _request_limit_exceeded(operation: str) -> None:
    """403, not 429 — Salesforce's actual behavior. See module docstring."""
    raise ProviderRateLimitError(
        "REQUEST_LIMIT_EXCEEDED: TotalRequests Limit exceeded.",
        provider=ProviderType.SALESFORCE.value,
        operation=operation,
        status_code_from_provider=403,
        retry_after_seconds=60.0,
    )


def _invalid_session(operation: str) -> None:
    raise ProviderAuthError(
        "INVALID_SESSION_ID: Session expired or invalid",
        refreshable=True,
        provider=ProviderType.SALESFORCE.value,
        operation=operation,
        status_code_from_provider=401,
    )


def _invalid_field(operation: str) -> None:
    raise PermanentProviderError(
        "INVALID_FIELD: No such column 'Onboarding_Stage__c' on entity 'Account'",
        provider=ProviderType.SALESFORCE.value,
        operation=operation,
        status_code_from_provider=400,
    )


def _insufficient_access(operation: str) -> None:
    raise PermanentProviderError(
        "INSUFFICIENT_ACCESS_OR_READONLY: insufficient access rights on object id",
        provider=ProviderType.SALESFORCE.value,
        operation=operation,
        status_code_from_provider=403,
    )


def _record_deleted(operation: str) -> None:
    raise PermanentProviderError(
        "ENTITY_IS_DELETED: entity is deleted",
        provider=ProviderType.SALESFORCE.value,
        operation=operation,
        status_code_from_provider=404,
    )


_SALESFORCE_SCENARIOS = {
    "sf_request_limit_exceeded": _request_limit_exceeded,
    "sf_invalid_session": _invalid_session,
    "sf_invalid_field": _invalid_field,
    "sf_insufficient_access": _insufficient_access,
    "sf_record_deleted": _record_deleted,
}

SALESFORCE_SCENARIO_NAMES = tuple(sorted(_SALESFORCE_SCENARIOS))

# Exported for seeds, tests and the demo script, so nothing has to hardcode
# a simulated ID and then drift when this file changes.
SIMULATED_ACCOUNT_ID = _ACCOUNT_ID
SIMULATED_CONTACT_ID = _CONTACT_ID
SIMULATED_OPPORTUNITY_ID = _OPPORTUNITY_ID
