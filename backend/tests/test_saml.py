"""SAML PoC validator — see app/core/saml.py and ADR-0021.

Real asymmetric crypto and a real signxml verification path throughout,
same reasoning as test_auth_modes.py's OIDC tests: a fake that "verifies"
everything tests nothing. IdP metadata is served from an in-memory fake
(_FakeMetadataCache), never HTTP, so this suite keeps needing nothing but
the test's own generated keypair.
"""

import base64
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from lxml import etree
from signxml import XMLSigner

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError
from app.core.saml import (
    NSMAP,
    SAML_NS,
    SAMLP_NS,
    IdPMetadata,
    SAMLValidator,
    _PendingRequestStore,
    build_authn_request_url,
)

SP_ENTITY_ID = "meridian-flow-saml"
ACS_URL = "http://localhost:8000/auth/saml/acs"
IDP_ISSUER = "http://keycloak:8080/realms/meridian"
SSO_URL = "http://keycloak:8080/realms/meridian/protocol/saml"


@pytest.fixture(scope="session")
def saml_keys() -> dict[str, Any]:
    """A self-signed RSA keypair the fake IdP metadata cache serves as
    Keycloak's signing certificate. Generated once per session — signing a
    keypair is not free, and nothing here needs a fresh one per test."""
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


@pytest.fixture(scope="session")
def other_saml_keys() -> dict[str, Any]:
    """A second, unrelated keypair — stands in for "an attacker's own key"
    or "the wrong IdP's key", never registered with the fake metadata
    cache the validator trusts."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "not-the-real-idp")])
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
    """Stands in for SAMLIdPMetadataCache without any HTTP."""

    def __init__(self, cert_pem: str, *, sso_url: str = SSO_URL) -> None:
        self._metadata = IdPMetadata(signing_certs=(cert_pem,), sso_redirect_url=sso_url)
        self.fetch_count = 0

    def get_metadata(self) -> IdPMetadata:
        self.fetch_count += 1
        return self._metadata


@pytest.fixture
def saml_settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    settings = get_settings()
    monkeypatch.setattr(settings, "saml_sp_entity_id", SP_ENTITY_ID)
    monkeypatch.setattr(settings, "saml_acs_url", ACS_URL)
    monkeypatch.setattr(settings, "oidc_issuer", IDP_ISSUER)
    monkeypatch.setattr(settings, "saml_leeway_seconds", 30)
    return settings


@pytest.fixture
def saml_validator(saml_settings: Any, saml_keys: dict[str, Any]) -> SAMLValidator:
    cache = _FakeMetadataCache(saml_keys["cert_pem"])
    return SAMLValidator(
        saml_settings, metadata_cache=cache, pending_requests=_PendingRequestStore()
    )


def _fmt(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_response(
    *,
    key_pem: str,
    cert_pem: str,
    in_response_to: str,
    name_id: str = "ava.thompson@cordant.io",
    issuer: str = IDP_ISSUER,
    audience: str = SP_ENTITY_ID,
    recipient: str = ACS_URL,
    not_before: datetime | None = None,
    not_on_or_after: datetime | None = None,
    confirmation_not_on_or_after: datetime | None = None,
    sign: bool = True,
    extra_response_children: str = "",
    assertion_count: int = 1,
    nest_assertion_one_level_deeper: bool = False,
) -> str:
    """Builds and (optionally) signs a minimal but spec-shaped SAMLResponse,
    returning it base64-encoded exactly as it would arrive in the
    SAMLResponse form field."""
    now = datetime.now(UTC)
    not_before = not_before or (now - timedelta(minutes=1))
    not_on_or_after = not_on_or_after or (now + timedelta(minutes=5))
    confirmation_not_on_or_after = confirmation_not_on_or_after or (now + timedelta(minutes=5))

    assertion_id = "_" + "a" * 32
    assertion_xml = (
        f'<saml:Assertion xmlns:saml="{SAML_NS}" ID="{assertion_id}" '
        f'IssueInstant="{_fmt(now)}" Version="2.0">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        f"<saml:Subject>"
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{name_id}</saml:NameID>"
        f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{_fmt(confirmation_not_on_or_after)}" '
        f'Recipient="{recipient}" InResponseTo="{in_response_to}"/>'
        f"</saml:SubjectConfirmation>"
        f"</saml:Subject>"
        f'<saml:Conditions NotBefore="{_fmt(not_before)}" NotOnOrAfter="{_fmt(not_on_or_after)}">'
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience>"
        f"</saml:AudienceRestriction>"
        f"</saml:Conditions>"
        f'<saml:AuthnStatement AuthnInstant="{_fmt(now)}" SessionIndex="sess-123"/>'
        f"</saml:Assertion>"
    )

    assertions_xml = assertion_xml * assertion_count
    if nest_assertion_one_level_deeper:
        assertions_xml = f"<Wrapper>{assertions_xml}</Wrapper>"

    response_xml = (
        f'<samlp:Response xmlns:samlp="{SAMLP_NS}" xmlns:saml="{SAML_NS}" '
        f'ID="_resp1" IssueInstant="{_fmt(now)}" Version="2.0">'
        f"{extra_response_children}"
        f"{assertions_xml}"
        f"</samlp:Response>"
    )
    response_root = etree.fromstring(response_xml.encode())

    if sign:
        # Sign each Assertion *in its final position in the tree*, not as
        # a standalone fragment stitched in afterward — exclusive c14n's
        # digest depends on the element's actual namespace context, and a
        # signature computed while the element was a lone document root
        # does not survive being relocated under a new parent (confirmed
        # empirically: signing standalone then string-concatenating the
        # result into a larger document breaks verification even though
        # nothing about the assertion's own content changed). Real IdPs
        # sign the assertion where it already lives in the response
        # they're building, so tests should construct signatures the same
        # way to actually exercise the verifier against realistic input.
        for unsigned in response_root.findall("saml:Assertion", namespaces=NSMAP):
            signed = XMLSigner(
                signature_algorithm="rsa-sha256",
                digest_algorithm="sha256",
            ).sign(unsigned, key=key_pem, cert=cert_pem, reference_uri="#" + assertion_id)
            unsigned.getparent().replace(unsigned, signed)

    return base64.b64encode(etree.tostring(response_root)).decode()


class TestAuthnRequestBuilder:
    def test_produces_a_deflated_base64_query_parameter(self) -> None:
        url = build_authn_request_url(
            sso_url=SSO_URL, sp_entity_id=SP_ENTITY_ID, acs_url=ACS_URL, request_id="_req1"
        )
        assert url.startswith(SSO_URL + "?SAMLRequest=")
        encoded = url.split("SAMLRequest=", 1)[1]
        from urllib.parse import unquote

        raw = zlib.decompressobj(-15).decompress(base64.b64decode(unquote(encoded)))
        assert b'ID="_req1"' in raw
        assert SP_ENTITY_ID.encode() in raw
        assert ACS_URL.encode() in raw


class TestStartLogin:
    def test_start_login_issues_a_pending_request_and_returns_a_redirect_url(
        self, saml_validator: SAMLValidator
    ) -> None:
        url = saml_validator.start_login()
        assert url.startswith(SSO_URL)
        assert "SAMLRequest=" in url


class TestValidateResponse:
    def test_valid_response_is_accepted(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"], cert_pem=saml_keys["cert_pem"], in_response_to=request_id
        )
        principal = saml_validator.validate_response(response)
        assert principal.name_id == "ava.thompson@cordant.io"
        assert principal.issuer == IDP_ISSUER
        assert principal.session_index == "sess-123"

    def test_unsigned_response_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            sign=False,
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_response_signed_by_an_untrusted_key_is_rejected(
        self,
        saml_validator: SAMLValidator,
        other_saml_keys: dict[str, Any],
    ) -> None:
        """The assertion is well-formed and internally consistent — signed
        with a real key, just not the one the fake IdP metadata cache
        trusts. Stands in for an attacker who controls their own keypair
        but not Keycloak's."""
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=other_saml_keys["key_pem"],
            cert_pem=other_saml_keys["cert_pem"],
            in_response_to=request_id,
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_expired_conditions_are_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            not_on_or_after=datetime.now(UTC) - timedelta(hours=1),
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_not_yet_valid_conditions_are_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            not_before=datetime.now(UTC) + timedelta(hours=1),
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_wrong_audience_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        """Token substitution's SAML analogue: an assertion Keycloak issued
        for a different SAML client in the same realm must not work here."""
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            audience="some-other-sp",
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_wrong_recipient_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            recipient="http://attacker.example.com/acs",
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_wrong_issuer_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            issuer="http://evil:8080/realms/other",
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_unknown_in_response_to_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        """No AuthnRequest was ever issued with this id — an IdP-initiated
        or forged response, not one this SP started."""
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to="_never_issued",
        )
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_replayed_response_is_rejected_on_second_use(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        """InResponseTo is one-time use: a captured SAMLResponse POSTed to
        the ACS twice must fail the second time even though every other
        check on it still passes."""
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"], cert_pem=saml_keys["cert_pem"], in_response_to=request_id
        )
        saml_validator.validate_response(response)
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(response)

    def test_zero_assertions_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            assertion_count=0,
        )
        with pytest.raises(InvalidTokenError, match="exactly one Assertion"):
            saml_validator.validate_response(response)

    def test_multiple_assertions_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        """The entry point for XML Signature Wrapping: a response carrying
        two Assertion elements — even if only one is genuinely signed —
        must be rejected outright rather than the code picking one."""
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            assertion_count=2,
        )
        with pytest.raises(InvalidTokenError, match="exactly one Assertion"):
            saml_validator.validate_response(response)

    def test_assertion_nested_under_an_extra_wrapper_is_rejected(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        """This module only looks for Assertion elements that are direct
        children of the Response — the shape a classic wrapping attack
        needs (moving the genuine, validly-signed assertion out of its
        expected position while leaving a forged element in its place)
        is rejected as "no assertion found" rather than silently accepted
        from wherever it ended up in the tree."""
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            nest_assertion_one_level_deeper=True,
        )
        with pytest.raises(InvalidTokenError, match="exactly one Assertion"):
            saml_validator.validate_response(response)

    def test_claims_are_read_from_the_verified_assertion_not_a_decoy_sibling(
        self, saml_validator: SAMLValidator, saml_keys: dict[str, Any]
    ) -> None:
        """The second half of the wrapping defense: even with a decoy
        NameID sitting in the response alongside the real Assertion (not
        inside any Assertion, so it doesn't trip the exactly-one-Assertion
        check), the identity this module reports must be the one from the
        signature-verified subtree, never anything read from elsewhere in
        the response."""
        request_id = saml_validator._pending.issue()  # noqa: SLF001
        decoy = f'<saml:NameID xmlns:saml="{SAML_NS}">evil@cordant.io</saml:NameID>'
        response = _build_response(
            key_pem=saml_keys["key_pem"],
            cert_pem=saml_keys["cert_pem"],
            in_response_to=request_id,
            name_id="ava.thompson@cordant.io",
            extra_response_children=decoy,
        )
        principal = saml_validator.validate_response(response)
        assert principal.name_id == "ava.thompson@cordant.io"

    def test_not_base64_is_rejected(self, saml_validator: SAMLValidator) -> None:
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response("not valid base64!!!")

    def test_not_xml_is_rejected(self, saml_validator: SAMLValidator) -> None:
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(base64.b64encode(b"not xml").decode())

    def test_wrong_root_element_is_rejected(self, saml_validator: SAMLValidator) -> None:
        payload = base64.b64encode(b"<not-a-saml-response/>").decode()
        with pytest.raises(InvalidTokenError):
            saml_validator.validate_response(payload)


class TestPendingRequestStore:
    def test_issue_then_consume_succeeds_once(self) -> None:
        store = _PendingRequestStore()
        request_id = store.issue()
        assert store.consume(request_id) is True
        assert store.consume(request_id) is False

    def test_unissued_id_is_never_consumable(self) -> None:
        store = _PendingRequestStore()
        assert store.consume("_never_issued") is False

    def test_expired_entries_are_swept(self) -> None:
        store = _PendingRequestStore(ttl_seconds=0)
        request_id = store.issue()
        # ttl_seconds=0 means every entry is already "expired" by the time
        # the next call sweeps — issue() itself sweeps before inserting, so
        # this checks the id issued a moment ago does not survive a second
        # sweep.
        store.issue()
        assert store.consume(request_id) is False
