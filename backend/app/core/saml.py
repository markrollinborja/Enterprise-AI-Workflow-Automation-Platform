"""SAML 2.0 SP-side proof of concept (V2 Module 4 remainder, ADR-0021).

Answers the same question oidc.py answers for OIDC tokens, for a different
protocol: *is this assertion one Keycloak issued, for this application,
about a user we should trust, right now?* Five checks, and skipping any one
of them is a real vulnerability, not a missing nicety.

**Signature**, verified against Keycloak's published signing certificate
(fetched from its SAML IdP metadata, the SAML analogue of JWKS). Without it
an assertion is XML anyone can write.

**Exactly one Assertion**, checked before signature verification even runs.
A response carrying two `<saml:Assertion>` elements — one real, one
attacker-supplied — is the entry point for XML Signature Wrapping: code
that reads "the" NameID from the response by tag name, rather than from the
specific element whose signature was actually checked, can be made to read
the attacker's element while the signature check passes on the real one.
Requiring exactly one assertion removes the ambiguity before it can be
exploited.

**Extraction only from the verified subtree.** `XMLVerifier.verify()`
returns the specific element it checked as `.signed_xml`. Every claim this
module trusts — NameID, Conditions, SubjectConfirmationData — is read from
that returned element, never from the original parsed response. This is the
second half of the wrapping defense: even with exactly one assertion,
reading claims from the pre-verification tree instead of the post-verification
result reopens the same class of bug the moment someone "simplifies" the
code by removing what looks like a redundant re-lookup.

**Conditions and confirmation timestamps**, with bounded leeway for clock
drift, same reasoning as oidc.py's leeway.

**Audience, Recipient, and one-time InResponseTo**, which together bind the
assertion to this SP, this ACS URL, and the specific login this SP started —
without them a valid assertion issued for some other purpose (a different
client in the realm, a different SP entirely, or a captured response
replayed a second time) would be accepted here.

Deliberately does not attempt encrypted assertions, single logout, or
metadata-based autoconfiguration of the SP side — see ADR-0021 for what a
PoC scoped this way is (and is not) claiming to prove.
"""

import base64
import binascii
import logging
import secrets
import threading
import time
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from xml.etree.ElementTree import ParseError

import httpx
from lxml import etree
from signxml import XMLVerifier
from signxml.exceptions import InvalidCertificate, InvalidDigest, InvalidInput, InvalidSignature

from app.core.config import Settings
from app.core.exceptions import InvalidTokenError

logger = logging.getLogger(__name__)

SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
SAMLP_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"

NSMAP = {"saml": SAML_NS, "samlp": SAMLP_NS, "ds": DS_NS, "md": MD_NS}

REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
EMAIL_NAMEID_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

# Exceptions signxml raises when a signature genuinely does not verify
# against the offered certificate — as opposed to a bug in how this module
# called signxml, which should not be silently swallowed alongside them.
_SIGNATURE_REJECTION_ERRORS = (InvalidSignature, InvalidDigest, InvalidCertificate, InvalidInput)


class SAMLUnavailableError(Exception):
    """The IdP's metadata or signing certificate could not be fetched.

    Mirrors oidc.py's OIDCUnavailableError, and for the same reason: the
    assertion in hand may be perfectly valid, with Keycloak simply
    unreachable at the moment this process tried to fetch or refresh its
    signing certificate. Surfaces as 503, not as a rejected login.
    """


@dataclass(frozen=True)
class SAMLPrincipal:
    """The verified identity carried by a valid assertion."""

    name_id: str
    session_index: str | None
    issuer: str


@dataclass(frozen=True)
class IdPMetadata:
    signing_certs: tuple[str, ...]
    sso_redirect_url: str


class _PendingRequestStore:
    """AuthnRequest IDs this SP generated, so the ACS can confirm a
    response's InResponseTo refers to a login this SP actually started
    rather than trusting whatever value the response carries.

    One-time use: `consume()` removes the id, so a captured SAMLResponse
    POSTed to the ACS a second time is rejected on its second attempt even
    if every other check would otherwise still pass.

    Deliberately in-process memory, not shared storage. Acceptable for a
    PoC route that is never AUTH_MODE's dispatch target and therefore never
    needs to survive a restart or work across multiple backend replicas —
    seeADR-0021 for why that scope line is where it is.
    """

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._ids: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        # Leading underscore: SAML IDs are xsd:ID-typed, which forbids a
        # leading digit — a random hex string alone could start with one.
        request_id = "_" + secrets.token_hex(16)
        with self._lock:
            self._sweep_locked()
            self._ids[request_id] = time.monotonic()
        return request_id

    def consume(self, request_id: str) -> bool:
        with self._lock:
            self._sweep_locked()
            return self._ids.pop(request_id, None) is not None

    def _sweep_locked(self) -> None:
        cutoff = time.monotonic() - self._ttl
        expired = [rid for rid, issued in self._ids.items() if issued < cutoff]
        for rid in expired:
            del self._ids[rid]


class SAMLIdPMetadataCache:
    """Fetches and caches Keycloak's SAML signing certificate(s) and SSO
    redirect endpoint from its IdP metadata descriptor.

    Same shape as oidc.py's JWKSCache, same reasoning: fetching on every
    login puts Keycloak in the hot path of authentication, and a cache that
    never expires turns a routine signing-key rotation into silent,
    unexplained login failures until someone restarts the process.
    """

    def __init__(
        self, *, metadata_url: str, cache_seconds: int, client: httpx.Client | None = None
    ) -> None:
        self._metadata_url = metadata_url
        self._cache_seconds = cache_seconds
        self._client = client or httpx.Client(timeout=10.0)
        self._metadata: IdPMetadata | None = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _fetch(self) -> None:
        try:
            response = self._client.get(self._metadata_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SAMLUnavailableError(f"Could not fetch SAML IdP metadata: {exc}") from exc

        try:
            root = etree.fromstring(response.content)
        except etree.XMLSyntaxError as exc:
            raise SAMLUnavailableError(f"SAML IdP metadata was not valid XML: {exc}") from exc

        certs = tuple(
            "".join(node.text.split())
            for node in root.findall(
                ".//md:IDPSSODescriptor/md:KeyDescriptor[@use='signing']//ds:X509Certificate",
                namespaces=NSMAP,
            )
            if node.text
        )
        if not certs:
            raise SAMLUnavailableError("SAML IdP metadata contained no signing certificate")

        sso_url = None
        for node in root.findall(
            ".//md:IDPSSODescriptor/md:SingleSignOnService", namespaces=NSMAP
        ):
            if node.get("Binding") == REDIRECT_BINDING:
                sso_url = node.get("Location")
                break
        if not sso_url:
            raise SAMLUnavailableError(
                "SAML IdP metadata contained no HTTP-Redirect SingleSignOnService"
            )

        self._metadata = IdPMetadata(signing_certs=certs, sso_redirect_url=sso_url)
        self._fetched_at = time.monotonic()
        logger.info(
            "Fetched SAML IdP metadata", extra={"cert_count": len(certs), "sso_url": sso_url}
        )

    def get_metadata(self) -> IdPMetadata:
        with self._lock:
            expired = time.monotonic() - self._fetched_at > self._cache_seconds
            if self._metadata is None or expired:
                self._fetch()
            assert self._metadata is not None  # noqa: S101 — set by _fetch or an exception was raised
            return self._metadata

    def invalidate(self) -> None:
        with self._lock:
            self._metadata = None
            self._fetched_at = 0.0


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_authn_request_url(
    *, sso_url: str, sp_entity_id: str, acs_url: str, request_id: str
) -> str:
    """HTTP-Redirect binding (SAML core 3.4.4.1): DEFLATE-compress the
    AuthnRequest XML, base64-encode it, and URL-encode the result into the
    IdP's SSO endpoint as the SAMLRequest query parameter.

    Unsigned, deliberately: the SAML client in
    infra/keycloak/realm-meridian.json sets saml.client.signature=false, so
    Keycloak neither requires nor checks a signature here. That is a
    reasonable PoC simplification, not a security gap in what this module
    actually relies on — an unsigned AuthnRequest lets an attacker *start* a
    login flow that still ends with Keycloak authenticating the real user
    against the real IdP; it does not let them forge the assertion that
    comes back, which is the part every other check in this file exists to
    verify.
    """
    issue_instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{SAMLP_NS}" xmlns:saml="{SAML_NS}" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{issue_instant}" '
        f'Destination="{_xml_escape(sso_url)}" '
        f'AssertionConsumerServiceURL="{_xml_escape(acs_url)}" '
        f'ProtocolBinding="{POST_BINDING}">'
        f"<saml:Issuer>{_xml_escape(sp_entity_id)}</saml:Issuer>"
        f'<samlp:NameIDPolicy Format="{EMAIL_NAMEID_FORMAT}" AllowCreate="false"/>'
        f"</samlp:AuthnRequest>"
    )
    compressor = zlib.compressobj(level=9, wbits=-15)  # raw DEFLATE, no zlib/gzip header
    deflated = compressor.compress(xml.encode("utf-8")) + compressor.flush()
    encoded = base64.b64encode(deflated).decode("ascii")
    return f"{sso_url}?{urlencode({'SAMLRequest': encoded})}"


def _parse_saml_timestamp(value: str) -> datetime:
    # Keycloak emits SAML timestamps as strict UTC ("...Z"), never with a
    # numeric offset — fromisoformat before Python 3.11 cannot parse a
    # trailing "Z" directly (this project targets 3.12 in prod; the "Z"
    # -> "+00:00" swap keeps this correct under 3.11 test environments
    # too, at zero behavioral cost on 3.12).
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SAMLValidator:
    """Builds outbound AuthnRequests and validates inbound SAMLResponses."""

    def __init__(
        self,
        settings: Settings,
        *,
        metadata_cache: SAMLIdPMetadataCache | None = None,
        pending_requests: _PendingRequestStore | None = None,
    ) -> None:
        self._sp_entity_id = settings.saml_sp_entity_id
        self._acs_url = settings.saml_acs_url
        self._expected_issuer = settings.oidc_issuer.rstrip("/")
        self._leeway = timedelta(seconds=settings.saml_leeway_seconds)

        metadata_url = settings.saml_idp_metadata_url.rstrip("/") or (
            f"{self._expected_issuer}/protocol/saml/descriptor"
        )
        self._metadata = metadata_cache or SAMLIdPMetadataCache(
            metadata_url=metadata_url,
            cache_seconds=settings.saml_metadata_cache_seconds,
        )
        self._pending = pending_requests if pending_requests is not None else _PendingRequestStore()

    def start_login(self) -> str:
        """Build the redirect URL that sends the browser to Keycloak's SAML
        SSO endpoint, recording the generated request id for the ACS to
        check against later."""
        metadata = self._metadata.get_metadata()
        request_id = self._pending.issue()
        return build_authn_request_url(
            sso_url=metadata.sso_redirect_url,
            sp_entity_id=self._sp_entity_id,
            acs_url=self._acs_url,
            request_id=request_id,
        )

    def validate_response(self, saml_response_b64: str) -> SAMLPrincipal:
        try:
            raw = base64.b64decode(saml_response_b64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise InvalidTokenError("SAMLResponse was not valid base64") from exc

        try:
            root = etree.fromstring(raw)
        except (etree.XMLSyntaxError, ParseError) as exc:
            raise InvalidTokenError("SAMLResponse was not valid XML") from exc

        if root.tag != f"{{{SAMLP_NS}}}Response":
            raise InvalidTokenError("SAMLResponse root element was not a samlp:Response")

        verified_assertion = self._verify_signature(root)
        principal = self._extract_and_check(verified_assertion)
        return principal

    def _verify_signature(self, response_root: etree._Element) -> etree._Element:
        # Exactly one Assertion, checked before any signature is verified —
        # see the module docstring's "Exactly one Assertion" section. A
        # response with zero or several is rejected outright rather than
        # picking "the first one" or "the one that happens to verify".
        assertions = response_root.findall("saml:Assertion", namespaces=NSMAP)
        if len(assertions) != 1:
            raise InvalidTokenError(
                f"SAMLResponse must contain exactly one Assertion, found {len(assertions)}"
            )
        assertion = assertions[0]

        metadata = self._metadata.get_metadata()
        last_error: Exception | None = None
        for cert in metadata.signing_certs:
            try:
                result = XMLVerifier().verify(assertion, x509_cert=cert)
            except _SIGNATURE_REJECTION_ERRORS as exc:
                last_error = exc
                continue

            if isinstance(result, list):
                # expect_references=1 (signxml's default) means a single
                # VerifyResult is the only shape a genuine Keycloak
                # assertion ever produces here — a list would mean the
                # signature covered more than one Reference, which is not
                # a shape this module's checks are written to trust.
                last_error = InvalidInput("Signature verification returned multiple results")
                continue

            return result.signed_xml

        logger.warning("SAML assertion signature did not verify", extra={"reason": str(last_error)})
        raise InvalidTokenError("SAML assertion signature could not be verified")

    def _extract_and_check(self, assertion: etree._Element) -> SAMLPrincipal:
        # Every read below is against `assertion` — the element signxml
        # returned as .signed_xml, never the original response tree. That
        # is the property the module docstring calls out as the second
        # half of the wrapping defense.
        issuer_el = assertion.find("saml:Issuer", namespaces=NSMAP)
        issuer = (issuer_el.text or "").strip() if issuer_el is not None else ""
        if not issuer or issuer.rstrip("/") != self._expected_issuer:
            raise InvalidTokenError("SAML assertion issuer did not match the configured IdP")

        name_id_el = assertion.find("saml:Subject/saml:NameID", namespaces=NSMAP)
        if name_id_el is None or not (name_id_el.text or "").strip():
            raise InvalidTokenError("SAML assertion carried no NameID")
        name_id = name_id_el.text.strip()

        confirmation_data = assertion.find(
            "saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData",
            namespaces=NSMAP,
        )
        if confirmation_data is None:
            raise InvalidTokenError("SAML assertion carried no SubjectConfirmationData")

        recipient = confirmation_data.get("Recipient")
        if recipient != self._acs_url:
            raise InvalidTokenError("SAML assertion was not confirmed for this ACS URL")

        in_response_to = confirmation_data.get("InResponseTo")
        if not in_response_to or not self._pending.consume(in_response_to):
            raise InvalidTokenError(
                "SAML assertion InResponseTo did not match a login this SP started"
            )

        now = datetime.now(UTC)

        confirmation_not_on_or_after = confirmation_data.get("NotOnOrAfter")
        if confirmation_not_on_or_after and now > _parse_saml_timestamp(
            confirmation_not_on_or_after
        ) + self._leeway:
            raise InvalidTokenError("SAML assertion's subject confirmation has expired")

        conditions = assertion.find("saml:Conditions", namespaces=NSMAP)
        if conditions is not None:
            not_before = conditions.get("NotBefore")
            not_on_or_after = conditions.get("NotOnOrAfter")
            if not_before and now < _parse_saml_timestamp(not_before) - self._leeway:
                raise InvalidTokenError("SAML assertion is not yet valid")
            if not_on_or_after and now > _parse_saml_timestamp(not_on_or_after) + self._leeway:
                raise InvalidTokenError("SAML assertion has expired")

            audiences = {
                (el.text or "").strip()
                for el in conditions.findall(
                    "saml:AudienceRestriction/saml:Audience", namespaces=NSMAP
                )
            }
            if audiences and self._sp_entity_id not in audiences:
                raise InvalidTokenError("SAML assertion audience did not match this SP")

        session_index = None
        authn_statement = assertion.find("saml:AuthnStatement", namespaces=NSMAP)
        if authn_statement is not None:
            session_index = authn_statement.get("SessionIndex")

        return SAMLPrincipal(name_id=name_id, session_index=session_index, issuer=issuer)
