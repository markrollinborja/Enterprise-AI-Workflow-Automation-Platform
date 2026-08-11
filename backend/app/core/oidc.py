"""OIDC access-token validation against Keycloak.

This is the security-critical half of Module 4. Everything here exists to
answer one question correctly: *is this bearer token one Keycloak issued for
this application, right now, to a user we should trust?*

Four checks, and skipping any one of them is a real vulnerability rather than
a missing nicety:

**Signature**, against Keycloak's published public key (JWKS). Without it a
token is a JSON object anyone can write.

**Issuer**, exactly matching our configured realm. Without it, a token from
*any* Keycloak realm — including one an attacker controls — is accepted.

**Audience**, matching our client. Without it, a token minted for a different
client in the same realm works here. That is token substitution, and it is
the check most often skipped, because Keycloak only populates `aud` when an
audience mapper is configured — so validation appears "broken" and gets
disabled instead of fixed. The realm export configures the mapper.

**Expiry**, with bounded leeway for clock drift.

Deliberately does not accept tokens issued by this app itself: `AUTH_MODE`
selects one validator or the other (ADR-0015). A validator that accepted
either would let an attacker choose which set of rules to be judged by.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import JWTError, jwt

from app.core.config import Settings
from app.core.exceptions import InvalidTokenError

logger = logging.getLogger(__name__)

# Only asymmetric algorithms. Never HS256 here: an HMAC token is verified
# with the same secret used to sign it, so accepting HS256 alongside RS256
# enables algorithm confusion — an attacker signs a token using the *public*
# key as an HMAC secret, and a verifier that trusts the header's `alg`
# accepts it. Restricting the allowed set is the documented mitigation.
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384")


class OIDCUnavailableError(Exception):
    """The identity provider could not be reached.

    Distinct from InvalidTokenError deliberately. The token may be perfectly
    valid and Keycloak simply down; conflating the two sends users off to
    reset credentials that were never the problem. Surfaces as 503, not 401.
    """


@dataclass(frozen=True)
class OIDCPrincipal:
    """The verified identity carried by a valid token."""

    subject: str
    email: str | None
    full_name: str | None
    realm_roles: tuple[str, ...]
    client_roles: tuple[str, ...]
    # Keycloak's session id. Recorded on audit events so a support engineer
    # can tie several actions to one login rather than to one user in
    # general — which is the question when investigating "was that them?"
    session_id: str | None = None


class JWKSCache:
    """Fetches and caches Keycloak's signing keys.

    Cached, because fetching JWKS per request puts Keycloak in the hot path
    of every authenticated call. Expiring, because Keycloak rotates signing
    keys and a cache that never expires turns a routine rotation into a
    total authentication outage — the kind that presents as "all our tokens
    suddenly became invalid" and takes an hour to trace.

    Also refetches once on an unknown `kid`, which is what makes rotation
    recover in seconds instead of waiting out the TTL: a token signed by a
    key we have never seen is precisely the signal that keys changed.
    """

    def __init__(
        self, *, jwks_uri: str, cache_seconds: int, client: httpx.Client | None = None
    ) -> None:
        self._jwks_uri = jwks_uri
        self._cache_seconds = cache_seconds
        self._client = client or httpx.Client(timeout=10.0)
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _fetch(self) -> None:
        try:
            response = self._client.get(self._jwks_uri)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OIDCUnavailableError(f"Could not fetch JWKS: {exc}") from exc

        keys = {key["kid"]: key for key in response.json().get("keys", []) if "kid" in key}
        if not keys:
            raise OIDCUnavailableError("JWKS response contained no usable keys")

        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.info("Fetched OIDC signing keys", extra={"key_count": len(keys)})

    def get_key(self, kid: str) -> dict[str, Any]:
        with self._lock:
            expired = time.monotonic() - self._fetched_at > self._cache_seconds
            if not self._keys or expired:
                self._fetch()

            key = self._keys.get(kid)
            if key is None:
                # Unknown key id — most likely a rotation we have not seen.
                # Exactly one refetch, then give up. Without that bound, a
                # token bearing a garbage kid would trigger a JWKS fetch on
                # every request, turning a malformed token into a denial of
                # service aimed at Keycloak.
                self._fetch()
                key = self._keys.get(kid)

            if key is None:
                raise InvalidTokenError("Token was signed with an unknown key")
            return key

    def invalidate(self) -> None:
        with self._lock:
            self._keys = {}
            self._fetched_at = 0.0


class OIDCValidator:
    """Validates Keycloak access tokens."""

    def __init__(self, settings: Settings, *, jwks_cache: JWKSCache | None = None) -> None:
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._audience = settings.oidc_audience
        self._client_id = settings.oidc_client_id
        self._leeway = settings.oidc_leeway_seconds
        self._jwks = jwks_cache or JWKSCache(
            jwks_uri=f"{self._issuer}/protocol/openid-connect/certs",
            cache_seconds=settings.oidc_jwks_cache_seconds,
        )

    def validate(self, token: str) -> OIDCPrincipal:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise InvalidTokenError("Token header could not be read") from exc

        algorithm = header.get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            # Rejected before verification is attempted. "none" and HS256
            # must never reach the verifier at all.
            raise InvalidTokenError(f"Unsupported token algorithm: {algorithm}")

        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("Token header carries no key id")

        key = self._jwks.get_key(kid)

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    # python-jose takes leeway inside options, not as a
                    # keyword argument — passing it as a kwarg raises
                    # TypeError rather than being ignored, which is at
                    # least a loud way to be wrong.
                    #
                    # Bounded and small: generous leeway means an expired
                    # token stays usable for that much longer, which is the
                    # opposite of what expiry is for.
                    "leeway": self._leeway,
                },
            )
        except JWTError as exc:
            # The specific reason is logged, never returned. Telling a
            # caller "audience mismatch" rather than "invalid token" hands
            # them a way to iterate toward a token that works.
            logger.warning("OIDC token rejected", extra={"reason": str(exc)})
            raise InvalidTokenError("Invalid or expired token") from exc

        return self._to_principal(claims)

    def _to_principal(self, claims: dict[str, Any]) -> OIDCPrincipal:
        subject = claims.get("sub")
        if not subject:
            raise InvalidTokenError("Token carries no subject")

        # Keycloak nests roles in two places with different meanings:
        # realm_access.roles are realm-wide, resource_access.<client>.roles
        # are scoped to one client. Both are read, because a realm export
        # can reasonably use either and a mapper that looked at only one
        # would silently ignore correctly-assigned roles.
        realm_roles = tuple(claims.get("realm_access", {}).get("roles", []))
        client_roles = tuple(
            claims.get("resource_access", {}).get(self._client_id, {}).get("roles", [])
        )

        return OIDCPrincipal(
            subject=str(subject),
            email=claims.get("email"),
            full_name=claims.get("name") or claims.get("preferred_username"),
            realm_roles=realm_roles,
            client_roles=client_roles,
            session_id=claims.get("sid"),
        )
