"""Route-level SAML PoC tests — see app/api/routes/saml.py and ADR-0021.

Complements test_saml.py's unit-level validator coverage by exercising the
two endpoints together against a real database. Deliberately self-contained
rather than importing test_saml.py's helpers — same convention
test_auth_modes.py already follows (its own local _create_user rather than
a shared one), which also sidesteps the pytest/ruff friction of importing a
fixture by name into a second module (the parameter that receives it reads
as redefining the import, per F811).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from lxml import etree
from signxml import XMLSigner
from sqlalchemy.orm import Session

from app.api.routes import saml as saml_routes
from app.core.config import get_settings
from app.core.saml import NSMAP, SAML_NS, SAMLP_NS, IdPMetadata, SAMLValidator
from app.core.security import decode_access_token, hash_password
from app.models.enums import UserRole
from app.models.user import User

SP_ENTITY_ID = "meridian-flow-saml"
ACS_URL = "http://localhost:8000/auth/saml/acs"
IDP_ISSUER = "http://keycloak:8080/realms/meridian"
SSO_URL = "http://keycloak:8080/realms/meridian/protocol/saml"
FRONTEND_REDIRECT_URL = "http://localhost:5173/auth/saml/callback"
TEST_PASSWORD = "CorrectHorse123!"


@pytest.fixture(scope="session")
def saml_keys() -> dict[str, Any]:
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-saml-idp")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(days=1))
        .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return {"key_pem": key_pem, "cert_pem": cert_pem}


class _FakeMetadataCache:
    def __init__(self, cert_pem: str, *, sso_url: str = SSO_URL) -> None:
        self._metadata = IdPMetadata(signing_certs=(cert_pem,), sso_redirect_url=sso_url)

    def get_metadata(self) -> IdPMetadata:
        return self._metadata


def _fmt(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_response(
    *,
    key_pem: str,
    cert_pem: str,
    in_response_to: str,
    name_id: str,
    sign: bool = True,
) -> str:
    """Builds and signs a minimal, spec-shaped SAMLResponse — see
    test_saml.py's module docstring for why the assertion is signed *in its
    final tree position* rather than standalone and stitched in afterward.
    """
    import base64

    now = datetime.now(UTC)
    assertion_id = "_" + "a" * 32
    assertion_xml = (
        f'<saml:Assertion xmlns:saml="{SAML_NS}" ID="{assertion_id}" '
        f'IssueInstant="{_fmt(now)}" Version="2.0">'
        f"<saml:Issuer>{IDP_ISSUER}</saml:Issuer>"
        f"<saml:Subject>"
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{name_id}</saml:NameID>"
        f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{_fmt(now + timedelta(minutes=5))}" '
        f'Recipient="{ACS_URL}" InResponseTo="{in_response_to}"/>'
        f"</saml:SubjectConfirmation>"
        f"</saml:Subject>"
        f'<saml:Conditions NotBefore="{_fmt(now - timedelta(minutes=1))}" '
        f'NotOnOrAfter="{_fmt(now + timedelta(minutes=5))}">'
        f"<saml:AudienceRestriction><saml:Audience>{SP_ENTITY_ID}</saml:Audience>"
        f"</saml:AudienceRestriction>"
        f"</saml:Conditions>"
        f"</saml:Assertion>"
    )

    response_xml = (
        f'<samlp:Response xmlns:samlp="{SAMLP_NS}" xmlns:saml="{SAML_NS}" '
        f'ID="_resp1" IssueInstant="{_fmt(now)}" Version="2.0">'
        f"{assertion_xml}"
        f"</samlp:Response>"
    )
    response_root = etree.fromstring(response_xml.encode())

    if sign:
        for unsigned in response_root.findall("saml:Assertion", namespaces=NSMAP):
            signed = XMLSigner(signature_algorithm="rsa-sha256", digest_algorithm="sha256").sign(
                unsigned, key=key_pem, cert=cert_pem, reference_uri="#" + assertion_id
            )
            unsigned.getparent().replace(unsigned, signed)

    return base64.b64encode(etree.tostring(response_root)).decode()


def _create_user(db: Session, *, email: str, role: UserRole) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(TEST_PASSWORD),
        full_name="Test User",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def saml_route_validator(
    monkeypatch: pytest.MonkeyPatch, saml_keys: dict[str, Any]
) -> SAMLValidator:
    """Wires app.api.routes.saml's module-level validator singleton to a
    fake IdP metadata cache, the same way test_auth_modes.py's
    oidc_validator fixture patches app.api.deps.get_oidc_validator — the
    route handlers call get_saml_validator(), never construct one
    themselves, so patching what that function returns is enough to keep
    every request in a test using a validator that never touches the
    network."""
    settings = get_settings()
    monkeypatch.setattr(settings, "saml_sp_entity_id", SP_ENTITY_ID)
    monkeypatch.setattr(settings, "saml_acs_url", ACS_URL)
    monkeypatch.setattr(settings, "oidc_issuer", IDP_ISSUER)
    monkeypatch.setattr(settings, "saml_frontend_redirect_url", FRONTEND_REDIRECT_URL)

    validator = SAMLValidator(settings, metadata_cache=_FakeMetadataCache(saml_keys["cert_pem"]))
    monkeypatch.setattr(saml_routes, "get_saml_validator", lambda: validator)
    return validator


class TestSamlLogin:
    def test_redirects_to_the_idp_sso_endpoint_with_a_samlrequest(
        self, client: TestClient, saml_route_validator: SAMLValidator
    ) -> None:
        response = client.get("/auth/saml/login", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith(SSO_URL)
        assert "SAMLRequest" in parse_qs(urlparse(location).query)


class TestSamlAcs:
    def test_valid_response_issues_a_working_local_token_and_redirects_to_the_frontend(
        self,
        client: TestClient,
        db_session: Session,
        saml_route_validator: SAMLValidator,
        saml_keys: dict[str, Any],
    ) -> None:
        user = _create_user(db_session, email="ava.thompson@cordant.io", role=UserRole.HR)
        request_id = saml_route_validator._pending.issue()  # noqa: SLF001
        saml_response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            name_id="ava.thompson@cordant.io",
        )

        response = client.post(
            "/auth/saml/acs", data={"SAMLResponse": saml_response}, follow_redirects=False
        )

        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith(f"{FRONTEND_REDIRECT_URL}?token=")
        token = parse_qs(urlparse(location).query)["token"][0]

        # The redirect carries a token in the same local-JWT format
        # AUTH_MODE=local already validates (ADR-0021) — proven here by
        # decoding it and using it against a real protected endpoint, not
        # just asserting its shape.
        payload = decode_access_token(token)
        assert payload.user_id == user.id

        me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "ava.thompson@cordant.io"

    def test_unprovisioned_identity_is_rejected(
        self,
        client: TestClient,
        db_session: Session,
        saml_route_validator: SAMLValidator,
        saml_keys: dict[str, Any],
    ) -> None:
        request_id = saml_route_validator._pending.issue()  # noqa: SLF001
        saml_response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            name_id="stranger@elsewhere.com",
        )

        response = client.post(
            "/auth/saml/acs", data={"SAMLResponse": saml_response}, follow_redirects=False
        )
        assert response.status_code == 401

    def test_deactivated_user_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        saml_route_validator: SAMLValidator,
        saml_keys: dict[str, Any],
    ) -> None:
        user = _create_user(db_session, email="gone@cordant.io", role=UserRole.HR)
        user.is_active = False
        db_session.commit()

        request_id = saml_route_validator._pending.issue()  # noqa: SLF001
        saml_response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            name_id="gone@cordant.io",
        )

        response = client.post(
            "/auth/saml/acs", data={"SAMLResponse": saml_response}, follow_redirects=False
        )
        assert response.status_code == 403

    def test_invalid_assertion_never_reaches_user_resolution(
        self,
        client: TestClient,
        db_session: Session,
        saml_route_validator: SAMLValidator,
        saml_keys: dict[str, Any],
    ) -> None:
        """A tampered/unsigned response is rejected by the validator
        itself; the route never even attempts to look up a User for it."""
        request_id = saml_route_validator._pending.issue()  # noqa: SLF001
        saml_response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            name_id="ava.thompson@cordant.io",
            sign=False,
        )
        response = client.post(
            "/auth/saml/acs", data={"SAMLResponse": saml_response}, follow_redirects=False
        )
        assert response.status_code == 401

    def test_missing_saml_response_field_is_a_client_error(self, client: TestClient) -> None:
        response = client.post("/auth/saml/acs", data={})
        assert response.status_code == 422
