"""Inbound event ingestion — HMAC, idempotency, and organization creation.

The tests that matter most here are the negative ones. An ingestion endpoint
that works on the happy path but accepts an unsigned request, or acts twice
on a retried delivery, is worse than no endpoint: it looks correct right up
until it quietly does the wrong thing in production.
"""

import hashlib
import hmac
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.enums import (
    ExternalEntityType,
    InboundEventStatus,
    OrganizationStatus,
    ProviderType,
    UserRole,
)
from app.models.organization import ExternalIdentity, Organization
from app.models.user import User
from app.repositories import organization_repo
from app.services.integrations.ingestion_service import slugify

TEST_SECRET = "test-n8n-shared-secret"
TEST_PASSWORD = "CorrectHorse123!"


@pytest.fixture(autouse=True)
def _configure_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the app at a known shared secret.

    get_settings is lru_cached, so the object is patched in place rather
    than the environment — changing the env after the cache is warm has no
    effect, which is a confusing way to lose an afternoon.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "n8n_webhook_secret", TEST_SECRET)


def _sign(body: bytes, secret: str = TEST_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(account_id: str = "001Sim0000000AccAAA", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "correlation_id": "n8n-exec-9001",
        "account": {
            "id": account_id,
            "name": "Cordant Industries",
            "website": "https://www.cordant.io/about",
        },
        "opportunity": {"id": "006Sim0000000OppAAA", "is_won": True},
    }
    payload.update(overrides)
    return payload


def _post(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "sf-001-closedwon-1",
    event_type: str = "organization.onboarding_requested",
    secret: str = TEST_SECRET,
    signature: str | None = None,
    omit_headers: tuple[str, ...] = (),
) -> Any:
    body = json.dumps(payload).encode()
    headers = {
        "X-Signature": signature if signature is not None else _sign(body, secret),
        "X-Idempotency-Key": idempotency_key,
        "X-Event-Type": event_type,
        "Content-Type": "application/json",
    }
    for header in omit_headers:
        headers.pop(header, None)
    return client.post("/inbound/events", content=body, headers=headers)


class TestSignatureVerification:
    def test_valid_signature_is_accepted(self, client: TestClient, db_session: Session) -> None:
        assert _post(client, _payload()).status_code == 200

    def test_missing_signature_is_rejected(self, client: TestClient, db_session: Session) -> None:
        response = _post(client, _payload(), omit_headers=("X-Signature",))
        assert response.status_code == 401

    def test_wrong_signature_is_rejected(self, client: TestClient, db_session: Session) -> None:
        response = _post(client, _payload(), signature="deadbeef")
        assert response.status_code == 401

    def test_signature_from_the_wrong_secret_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        response = _post(client, _payload(), secret="not-the-shared-secret")
        assert response.status_code == 401

    def test_sha256_prefix_is_accepted(self, client: TestClient, db_session: Session) -> None:
        """Senders differ on whether they prefix the digest; failing over
        formatting would be an integration outage for a cosmetic reason."""
        body = json.dumps(_payload()).encode()
        response = client.post(
            "/inbound/events",
            content=body,
            headers={
                "X-Signature": f"sha256={_sign(body)}",
                "X-Idempotency-Key": "sf-prefixed-1",
                "X-Event-Type": "organization.onboarding_requested",
            },
        )
        assert response.status_code == 200

    def test_tampered_body_fails_verification(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Signature is over the raw bytes, so changing one field after
        signing must invalidate it."""
        original = json.dumps(_payload()).encode()
        tampered = json.dumps(_payload(account_id="001Attacker00000")).encode()
        response = client.post(
            "/inbound/events",
            content=tampered,
            headers={
                "X-Signature": _sign(original),
                "X-Idempotency-Key": "sf-tampered-1",
                "X-Event-Type": "organization.onboarding_requested",
            },
        )
        assert response.status_code == 401

    def test_unconfigured_secret_rejects_rather_than_disables(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure mode that turns a config mistake into an open
        endpoint. An empty secret must reject, never accept."""
        monkeypatch.setattr(get_settings(), "n8n_webhook_secret", "")
        assert _post(client, _payload()).status_code == 401


class TestIdempotency:
    def test_first_delivery_is_processed(self, client: TestClient, db_session: Session) -> None:
        response = _post(client, _payload(), idempotency_key="sf-idem-1")
        assert response.status_code == 200
        assert response.json()["status"] == "processed"

    def test_repeated_delivery_is_a_recognized_duplicate(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A provider retrying because it never saw our acknowledgement is
        behaving correctly — this must succeed, not error."""
        _post(client, _payload(), idempotency_key="sf-idem-2")
        second = _post(client, _payload(), idempotency_key="sf-idem-2")

        assert second.status_code == 208
        assert second.json()["status"] == "duplicate"
        assert second.json()["duplicate_of_id"] is not None

    def test_duplicate_does_not_create_a_second_organization(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The business consequence of the whole mechanism."""
        for _ in range(3):
            _post(client, _payload(account_id="001DupCheck0000AAA"), idempotency_key="sf-idem-3")

        organizations = (
            db_session.query(Organization).filter(Organization.name == "Cordant Industries").all()
        )
        assert len(organizations) == 1

    def test_different_keys_are_separate_events(
        self, client: TestClient, db_session: Session
    ) -> None:
        first = _post(client, _payload(), idempotency_key="sf-idem-4a")
        second = _post(client, _payload(), idempotency_key="sf-idem-4b")
        assert first.json()["id"] != second.json()["id"]

    def test_same_account_twice_reuses_the_organization(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Two genuinely distinct events about the same account must map to
        one organization — idempotency by external ID, not just by key."""
        _post(client, _payload(account_id="001Reuse00000AAAA"), idempotency_key="sf-reuse-1")
        _post(client, _payload(account_id="001Reuse00000AAAA"), idempotency_key="sf-reuse-2")

        identities = (
            db_session.query(ExternalIdentity)
            .filter(ExternalIdentity.external_id == "001Reuse00000AAAA")
            .all()
        )
        assert len(identities) == 1


class TestValidation:
    def test_missing_idempotency_key_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        response = _post(client, _payload(), omit_headers=("X-Idempotency-Key",))
        assert response.status_code == 400

    def test_missing_event_type_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        response = _post(client, _payload(), omit_headers=("X-Event-Type",))
        assert response.status_code == 400

    def test_invalid_json_is_rejected_after_signature_check(
        self, client: TestClient, db_session: Session
    ) -> None:
        body = b"{not json"
        response = client.post(
            "/inbound/events",
            content=body,
            headers={
                "X-Signature": _sign(body),
                "X-Idempotency-Key": "sf-badjson-1",
                "X-Event-Type": "organization.onboarding_requested",
            },
        )
        assert response.status_code == 400

    def test_payload_missing_account_is_unprocessable_but_recorded(
        self, client: TestClient, db_session: Session
    ) -> None:
        """422 so n8n can route it to failure escalation — and the row
        survives, because an event we failed to process is a support ticket
        while an event we never recorded is a mystery."""
        response = _post(
            client, {"correlation_id": "x", "account": {}}, idempotency_key="sf-noacct-1"
        )
        assert response.status_code == 422

        from app.repositories import inbound_event_repo

        event = inbound_event_repo.get_by_idempotency_key(db_session, "sf-noacct-1")
        assert event is not None
        assert event.status is InboundEventStatus.FAILED

    def test_unknown_event_type_is_recorded_not_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A sender adding a new event type should not start receiving
        errors from us; the row is evidence we saw something unfamiliar."""
        response = _post(
            client, _payload(), idempotency_key="sf-unknown-1", event_type="something.new"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "failed"

    def test_oversized_payload_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        body = json.dumps({"blob": "x" * 300_000}).encode()
        response = client.post(
            "/inbound/events",
            content=body,
            headers={
                "X-Signature": _sign(body),
                "X-Idempotency-Key": "sf-big-1",
                "X-Event-Type": "organization.onboarding_requested",
            },
        )
        assert response.status_code == 413


class TestOrganizationCreation:
    def test_organization_is_created_with_onboarding_status(
        self, client: TestClient, db_session: Session
    ) -> None:
        """ONBOARDING, not ACTIVE — the relationship exists but nothing has
        been set up yet."""
        _post(client, _payload(account_id="001Status000000AAA"), idempotency_key="sf-status-1")
        organization = organization_repo.get_by_external_id(
            db_session, system=ProviderType.SALESFORCE, external_id="001Status000000AAA"
        )
        assert organization is not None
        assert organization.status is OrganizationStatus.ONBOARDING

    def test_external_identity_is_linked(
        self, client: TestClient, db_session: Session
    ) -> None:
        _post(client, _payload(account_id="001Link00000000AAA"), idempotency_key="sf-link-1")
        identity = (
            db_session.query(ExternalIdentity)
            .filter(ExternalIdentity.external_id == "001Link00000000AAA")
            .one()
        )
        assert identity.system is ProviderType.SALESFORCE
        assert identity.entity_type is ExternalEntityType.ORGANIZATION

    def test_website_is_reduced_to_a_domain(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Salesforce does not validate its Website field, so it arrives as
        anything. A stored domain is matchable; a stored URL is not."""
        _post(client, _payload(account_id="001Domain00000AAA"), idempotency_key="sf-domain-1")
        organization = organization_repo.get_by_external_id(
            db_session, system=ProviderType.SALESFORCE, external_id="001Domain00000AAA"
        )
        assert organization is not None
        assert organization.primary_domain == "cordant.io"

    def test_correlation_id_from_the_caller_is_preserved(
        self, client: TestClient, db_session: Session
    ) -> None:
        """n8n minted the ID before calling us and its own execution log
        records that value — overwriting it breaks the join between the two
        systems, which is the entire point."""
        response = _post(client, _payload(), idempotency_key="sf-corr-1")
        assert response.json()["correlation_id"] == "n8n-exec-9001"


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Cordant Industries", "cordant-industries"),
            ("  Spaced  Out  ", "spaced-out"),
            ("Ünïcödé & Symbols!", "n-c-d-symbols"),
            ("ALL CAPS CO", "all-caps-co"),
        ],
    )
    def test_produces_url_safe_keys(self, name: str, expected: str) -> None:
        assert slugify(name) == expected

    def test_punctuation_only_name_still_yields_a_slug(self) -> None:
        """An empty slug would violate NOT NULL and turn a naming oddity
        into a 500."""
        assert slugify("!!!") == "organization"

    def test_slug_collisions_get_a_suffix(self, db_session: Session) -> None:
        """Two customers whose names slugify identically must both be able
        to onboard."""
        first = organization_repo.create_with_external_identity(
            db_session,
            name="Cordant Industries",
            slug="cordant-industries",
            system=ProviderType.SALESFORCE,
            external_id=f"001{uuid.uuid4().hex[:12]}",
        )
        second = organization_repo.create_with_external_identity(
            db_session,
            name="Cordant, Industries!",
            slug="cordant-industries",
            system=ProviderType.SALESFORCE,
            external_id=f"001{uuid.uuid4().hex[:12]}",
        )
        assert first.slug != second.slug


class TestSupportConsoleLookups:
    def _headers(self, client: TestClient, db: Session, role: UserRole, email: str) -> Any:
        db.add(
            User(
                email=email,
                hashed_password=hash_password(TEST_PASSWORD),
                full_name="Test User",
                role=role,
            )
        )
        db.commit()
        token = client.post(
            "/auth/login", json={"email": email, "password": TEST_PASSWORD}
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_events_can_be_found_by_correlation_id(
        self, client: TestClient, db_session: Session
    ) -> None:
        _post(client, _payload(), idempotency_key="sf-lookup-1")
        headers = self._headers(client, db_session, UserRole.IT, "it-inbound@cordant.io")

        response = client.get("/inbound/events/by-correlation/n8n-exec-9001", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_listing_events_requires_an_operator_role(
        self, client: TestClient, db_session: Session
    ) -> None:
        headers = self._headers(client, db_session, UserRole.EMPLOYEE, "emp-inbound@cordant.io")
        assert client.get("/inbound/events", headers=headers).status_code == 403
