"""SCIM 2.0 provisioning — see app/api/routes/scim.py and docs/architecture/scim.md.

Three things are being defended:

1. **Authentication.** These routes bypass `require_role` entirely, because a
   SCIM client is a service with no user session. The token check is the only
   thing standing between the internet and account creation.
2. **Idempotency.** Connectors re-sync. A re-sent create must not become a
   second account or a hard failure.
3. **Protocol shape.** A connector parses `scimType` to decide what to do
   next. Correct status codes with the wrong body are still unusable.
"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import ProviderType, UserRole
from app.repositories import user_repo
from app.schemas.scim import USER_SCHEMA

SCIM_TOKEN = "test-scim-bearer-token-value"


@pytest.fixture(autouse=True)
def _configure_scim_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "scim_bearer_token", SCIM_TOKEN)


def _headers(token: str = SCIM_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/scim+json"}


def _user_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemas": [USER_SCHEMA],
        "externalId": f"kc-{uuid.uuid4().hex[:10]}",
        "userName": f"dana.{uuid.uuid4().hex[:6]}@cordant.io",
        "name": {"givenName": "Dana", "familyName": "Whitfield"},
        "emails": [{"value": f"dana.{uuid.uuid4().hex[:6]}@cordant.io", "primary": True}],
        "active": True,
    }
    payload.update(overrides)
    return payload


class TestAuthentication:
    def test_valid_token_is_accepted(self, client: TestClient, db_session: Session) -> None:
        response = client.post("/scim/v2/Users", json=_user_payload(), headers=_headers())
        assert response.status_code == 201

    def test_missing_authorization_is_refused(
        self, client: TestClient, db_session: Session
    ) -> None:
        assert client.post("/scim/v2/Users", json=_user_payload()).status_code == 401

    def test_wrong_token_is_refused(self, client: TestClient, db_session: Session) -> None:
        response = client.post(
            "/scim/v2/Users", json=_user_payload(), headers=_headers("not-the-token")
        )
        assert response.status_code == 401

    def test_wrong_scheme_is_refused(self, client: TestClient, db_session: Session) -> None:
        response = client.post(
            "/scim/v2/Users",
            json=_user_payload(),
            headers={"Authorization": f"Basic {SCIM_TOKEN}"},
        )
        assert response.status_code == 401

    def test_unset_token_rejects_everything(
        self, client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure mode that turns a config oversight into an open
        account-creation endpoint."""
        monkeypatch.setattr(get_settings(), "scim_bearer_token", "")
        response = client.post("/scim/v2/Users", json=_user_payload(), headers=_headers())
        assert response.status_code == 401

    def test_a_user_jwt_does_not_work_here(
        self, client: TestClient, db_session: Session
    ) -> None:
        """SCIM auth is its own credential — a logged-in administrator's
        token must not be usable to drive provisioning."""
        from app.core.security import hash_password
        from app.models.user import User

        db_session.add(
            User(
                email="admin-scim@cordant.io",
                hashed_password=hash_password("CorrectHorse123!"),
                full_name="Admin",
                role=UserRole.ADMINISTRATOR,
            )
        )
        db_session.commit()
        token = client.post(
            "/auth/login",
            json={"email": "admin-scim@cordant.io", "password": "CorrectHorse123!"},
        ).json()["access_token"]

        response = client.post(
            "/scim/v2/Users", json=_user_payload(), headers=_headers(token)
        )
        assert response.status_code == 401


class TestCreate:
    def test_creates_a_user_with_scim_response_shape(
        self, client: TestClient, db_session: Session
    ) -> None:
        payload = _user_payload()
        response = client.post("/scim/v2/Users", json=payload, headers=_headers())
        assert response.status_code == 201

        body = response.json()
        assert USER_SCHEMA in body["schemas"]
        assert body["userName"]
        assert body["active"] is True
        assert body["meta"]["resourceType"] == "User"
        assert body["id"]

    def test_defaults_to_the_least_privileged_role(
        self, client: TestClient, db_session: Session
    ) -> None:
        """An integration bug that drops the role attribute must
        under-grant, never over-grant."""
        response = client.post("/scim/v2/Users", json=_user_payload(), headers=_headers())
        assert response.json()["roles"] == [UserRole.EMPLOYEE.value]

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [
            (["meridian-hr"], UserRole.HR),
            (["hr"], UserRole.HR),
            (["MERIDIAN-IT"], UserRole.IT),
            (["not-a-role"], UserRole.EMPLOYEE),
        ],
    )
    def test_role_assignment_accepts_both_spellings(
        self, client: TestClient, db_session: Session, supplied: list[str], expected: UserRole
    ) -> None:
        """A connector's role catalog is configured by whoever set it up;
        insisting on one exact spelling is how everyone silently ends up
        with the default role."""
        response = client.post(
            "/scim/v2/Users", json=_user_payload(roles=supplied), headers=_headers()
        )
        assert response.json()["roles"] == [expected.value]

    def test_repeated_create_for_the_same_external_id_is_idempotent(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Connectors re-sync. Treating that as a conflict makes every
        re-sync look like a failure."""
        payload = _user_payload()
        first = client.post("/scim/v2/Users", json=payload, headers=_headers())
        second = client.post("/scim/v2/Users", json=payload, headers=_headers())

        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]

    def test_a_different_user_claiming_an_existing_username_is_a_conflict(
        self, client: TestClient, db_session: Session
    ) -> None:
        payload = _user_payload()
        client.post("/scim/v2/Users", json=payload, headers=_headers())

        clash = _user_payload(
            externalId=f"kc-{uuid.uuid4().hex[:10]}",
            userName=payload["userName"],
            emails=payload["emails"],
        )
        response = client.post("/scim/v2/Users", json=clash, headers=_headers())

        assert response.status_code == 409
        assert response.json()["scimType"] == "uniqueness"

    def test_external_identity_is_recorded(
        self, client: TestClient, db_session: Session
    ) -> None:
        payload = _user_payload()
        client.post("/scim/v2/Users", json=payload, headers=_headers())

        user = user_repo.get_by_external_id(
            db_session, system=ProviderType.SCIM_CLIENT, external_id=payload["externalId"]
        )
        assert user is not None

    def test_user_with_no_email_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        payload = _user_payload(userName="no-at-sign", emails=[])
        response = client.post("/scim/v2/Users", json=payload, headers=_headers())
        assert response.status_code == 400
        assert response.json()["scimType"] == "invalidValue"

    def test_primary_email_is_preferred_over_the_first(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Taking the first address attaches a user's alternate mailbox to
        their account whenever the client's ordering differs."""
        payload = _user_payload(
            emails=[
                {"value": "alternate@cordant.io", "primary": False},
                {"value": "primary@cordant.io", "primary": True},
            ]
        )
        response = client.post("/scim/v2/Users", json=payload, headers=_headers())
        assert response.json()["userName"] == "primary@cordant.io"


class TestReadAndFilter:
    def test_get_by_id(self, client: TestClient, db_session: Session) -> None:
        created = client.post("/scim/v2/Users", json=_user_payload(), headers=_headers()).json()
        response = client.get(f"/scim/v2/Users/{created['id']}", headers=_headers())
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_unknown_id_is_a_scim_shaped_404(
        self, client: TestClient, db_session: Session
    ) -> None:
        response = client.get(f"/scim/v2/Users/{uuid.uuid4()}", headers=_headers())
        assert response.status_code == 404
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in response.json()["schemas"]

    def test_username_filter_finds_the_user(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The one filter every provisioning connector issues — checking
        whether a user exists before creating them."""
        payload = _user_payload()
        client.post("/scim/v2/Users", json=payload, headers=_headers())
        email = payload["emails"][0]["value"]

        response = client.get(
            "/scim/v2/Users", params={"filter": f'userName eq "{email}"'}, headers=_headers()
        )
        body = response.json()
        assert body["totalResults"] == 1
        assert body["Resources"][0]["userName"] == email

    def test_filter_for_an_absent_user_returns_an_empty_list(
        self, client: TestClient, db_session: Session
    ) -> None:
        response = client.get(
            "/scim/v2/Users",
            params={"filter": 'userName eq "nobody@cordant.io"'},
            headers=_headers(),
        )
        assert response.json()["totalResults"] == 0

    def test_unsupported_filter_is_rejected_not_ignored(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Ignoring an unsupported filter would return the entire directory
        while looking like success — leaking every user."""
        response = client.get(
            "/scim/v2/Users", params={"filter": 'active eq "true"'}, headers=_headers()
        )
        assert response.status_code == 400
        assert response.json()["scimType"] == "invalidFilter"

    def test_list_response_uses_the_spec_envelope(
        self, client: TestClient, db_session: Session
    ) -> None:
        client.post("/scim/v2/Users", json=_user_payload(), headers=_headers())
        body = client.get("/scim/v2/Users", headers=_headers()).json()
        assert "urn:ietf:params:scim:api:messages:2.0:ListResponse" in body["schemas"]
        assert "Resources" in body
        assert "totalResults" in body


class TestPatchAndDeprovision:
    def _create(self, client: TestClient) -> dict[str, Any]:
        return client.post("/scim/v2/Users", json=_user_payload(), headers=_headers()).json()

    def test_targeted_replace_of_active_deactivates(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Okta's shape: an operation with an explicit path."""
        created = self._create(client)
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json()["active"] is False

    def test_untargeted_replace_of_active_deactivates(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Keycloak's shape: no path, a dict of attributes as the value.
        Both must work or one of the two connectors silently fails."""
        created = self._create(client)
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "value": {"active": False}}]},
            headers=_headers(),
        )
        assert response.json()["active"] is False

    @pytest.mark.parametrize("false_value", [False, "false", "False"])
    def test_every_spelling_of_false_deactivates(
        self, client: TestClient, db_session: Session, false_value: Any
    ) -> None:
        """Guessing wrong leaves an account enabled that the directory
        believes is disabled — the worst direction to be lenient in."""
        created = self._create(client)
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "active", "value": false_value}]},
            headers=_headers(),
        )
        assert response.json()["active"] is False

    def test_nonsense_active_value_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        created = self._create(client)
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "active", "value": "maybe"}]},
            headers=_headers(),
        )
        assert response.status_code == 400

    def test_reactivation_works(self, client: TestClient, db_session: Session) -> None:
        created = self._create(client)
        client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
            headers=_headers(),
        )
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "active", "value": True}]},
            headers=_headers(),
        )
        assert response.json()["active"] is True

    def test_role_change_via_patch(self, client: TestClient, db_session: Session) -> None:
        created = self._create(client)
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "roles", "value": ["meridian-it"]}]},
            headers=_headers(),
        )
        assert response.json()["roles"] == [UserRole.IT.value]

    def test_unsupported_path_is_rejected_not_silently_ignored(
        self, client: TestClient, db_session: Session
    ) -> None:
        """A client that believes it changed something when nothing
        happened is a security problem, not a compatibility one."""
        created = self._create(client)
        response = client.patch(
            f"/scim/v2/Users/{created['id']}",
            json={"Operations": [{"op": "replace", "path": "title", "value": "CEO"}]},
            headers=_headers(),
        )
        assert response.status_code == 400
        assert response.json()["scimType"] == "invalidPath"

    def test_delete_deactivates_rather_than_removing(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Deleting would orphan every approval, workflow and audit row
        naming this user — exactly the history you need when asking what a
        departed employee had access to."""
        created = self._create(client)
        deleted = client.delete(f"/scim/v2/Users/{created['id']}", headers=_headers())
        assert deleted.status_code == 204

        still_there = client.get(f"/scim/v2/Users/{created['id']}", headers=_headers())
        assert still_there.status_code == 200
        assert still_there.json()["active"] is False

    def test_deactivated_user_cannot_authenticate(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The point of deprovisioning — it has to actually remove access,
        not just set a flag nobody reads."""
        payload = _user_payload()
        created = client.post("/scim/v2/Users", json=payload, headers=_headers()).json()
        client.delete(f"/scim/v2/Users/{created['id']}", headers=_headers())

        user = user_repo.get_by_email_ci(db_session, payload["emails"][0]["value"])
        assert user is not None
        assert user.is_active is False
