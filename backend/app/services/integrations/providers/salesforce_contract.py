"""The Salesforce contract — what both the live adapter and the simulator
must satisfy.

Split into its own module so the contract is a written artifact rather than
"whatever the live adapter happens to do". The two implementations are tested
against this same interface (see tests/test_salesforce_contract.py), which is
what makes the simulator a faithful stand-in instead of a stub that drifts
the moment the real adapter changes.

The record shapes here are *normalized* — `SalesforceAccount`, not a raw
Salesforce JSON dict. Salesforce's own payloads carry `attributes` blocks,
inconsistent null handling, and field names that only mean something inside
Salesforce. Normalizing at the adapter boundary keeps that vocabulary out of
the workflow engine, and means a future provider (HubSpot, Dynamics) can
satisfy the same contract without the domain layer noticing.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SalesforceAccount:
    """A customer account, normalized."""

    external_id: str
    name: str
    website: str | None = None
    industry: str | None = None
    # Salesforce's own "last modified" for the record, used to decide
    # whether an inbound event is stale relative to what we already hold.
    last_modified: str | None = None


@dataclass(frozen=True)
class SalesforceContact:
    """A person attached to an account, normalized."""

    external_id: str
    account_external_id: str
    first_name: str | None
    last_name: str
    email: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class SalesforceOpportunity:
    """A deal, normalized.

    `is_won` is derived by the adapter rather than exposing the raw
    `StageName` string: every Salesforce org renames its stages, so a
    domain layer that checks `stage == "Closed Won"` is one admin's
    customization away from silently never triggering. The adapter reads
    `IsWon`, which is a real boolean on the object and cannot be renamed.
    """

    external_id: str
    name: str
    account_external_id: str | None
    stage_name: str
    is_won: bool
    is_closed: bool
    amount: float | None = None


@runtime_checkable
class SalesforceClient(Protocol):
    """Operations Meridian Flow needs from Salesforce.

    Deliberately read-only. V2's Salesforce integration consumes customer
    data to drive onboarding; it does not write back. That is a scope
    decision, not an oversight — write access to a CRM is where an
    integration bug stops being embarrassing and starts being expensive,
    and nothing in the demonstration requires it. Documented in the
    Salesforce guide as an explicit non-goal.
    """

    @abstractmethod
    def get_account(self, external_id: str) -> SalesforceAccount:
        """Fetch one account by Salesforce ID.

        Raises PermanentProviderError if no such account exists — a missing
        record will still be missing on retry.
        """

    @abstractmethod
    def list_contacts_for_account(self, account_external_id: str) -> list[SalesforceContact]:
        """Contacts attached to an account. Empty list is a valid answer."""

    @abstractmethod
    def get_opportunity(self, external_id: str) -> SalesforceOpportunity:
        """Fetch one opportunity by Salesforce ID."""

    @abstractmethod
    def api_version(self) -> str:
        """The API version this client is talking to.

        Part of the contract because it is recorded on every sync as
        evidence: "which API version produced this data" is unanswerable
        later otherwise, and it is the first question when a field starts
        arriving empty after a Salesforce release.
        """
