"""Dual-mode authentication — see ADR-0015 and app/api/deps.py.

The important test in this file is `TestRbacParity`. Dual-mode auth is only
defensible if both paths reach the *same* authorization decisions; two
mechanisms that agree on authentication but drift on authorization is
strictly worse than one mechanism, because the divergence is invisible until
someone gets access they should not have. That class runs identical RBAC
assertions through local JWT and through OIDC and requires identical answers.

OIDC tokens here are signed with a locally-generated RSA key and served
through a fake JWKS, so the whole validation path — signature, issuer,
audience, expiry, claim mapping — is exercised without Keycloak running. The
test suite must keep needing nothing but PostgreSQL.
"""

import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.orm import Session

from app.api import deps
from app.core.auth_mode import (
    AuthMode,
    AuthModeConfigurationError,
    resolve_auth_mode,
    validate_auth_configuration,
)
from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError
from app.core.oidc import OIDCPrincipal, OIDCValidator
from app.core.security import hash_password
from app.models.enums import ExternalEntityType, ProviderType, UserRole
from app.models.organization import ExternalIdentity
from app.models.user import User
from app.services.auth import oidc_resolver

ISSUER = "http://keycloak:8080/realms/meridian"
AUDIENCE = "meridian-flow"
CLIENT_ID = "meridian-flow"
TEST_PASSWORD = "CorrectHorse123!"
KID = "test-signing-key"


# --------------------------------------------------------------------------
# RSA keypair + fake JWKS, generated once per session. Real asymmetric
# crypto rather than a stub: the point is to exercise python-jose's actual
# verification, and a fake that "verifies" everything would test nothing.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def rsa_keys() -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwk

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    public_jwk = jwk.construct(public_pem, algorithm="RS256").to_dict()
    public_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"private_pem": private_pem, "public_jwk": public_jwk}


class _FakeJWKSCache:
    """Stands in for the real cache without any HTTP."""

    def __init__(self, key: dict[str, Any]) -> None:
        self._key = key
        self.fetch_count = 0

    def get_key(self, kid: str) -> dict[str, Any]:
        self.fetch_count += 1
        if kid != KID:
            raise InvalidTokenError("Token was signed with an unknown key")
        return self._key

    def invalidate(self) -> None:
        pass


def _make_token(
    rsa_keys: dict[str, Any],
    *,
    subject: str,
    email: str,
    roles: list[str],
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_in: int = 300,
    algorithm: str = "RS256",
    kid: str = KID,
) -> str:
    now = int(time.time())
    claims = {
        "sub": subject,
        "email": email,
        "name": "Test Person",
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "sid": "session-abc",
        "realm_access": {"roles": [*roles, "offline_access", "uma_authorization"]},
    }
    return jwt.encode(
        claims, rsa_keys["private_pem"], algorithm=algorithm, headers={"kid": kid}
    )


@pytest.fixture
def oidc_settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_audience", AUDIENCE)
    monkeypatch.setattr(settings, "oidc_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "oidc_client_secret", "test-client-secret")
    return settings


@pytest.fixture
def oidc_validator(oidc_settings: Any, rsa_keys: dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    validator = OIDCValidator(oidc_settings, jwks_cache=_FakeJWKSCache(rsa_keys["public_jwk"]))
    monkeypatch.setattr(deps, "get_oidc_validator", lambda: validator)
    return validator


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


def _link_keycloak_subject(db: Session, user: User, subject: str) -> None:
    db.add(
        ExternalIdentity(
            system=ProviderType.KEYCLOAK,
            entity_type=ExternalEntityType.USER,
            entity_id=user.id,
            external_id=subject,
        )
    )
    db.commit()


class TestAuthModeConfiguration:
    def test_local_is_the_default(self) -> None:
        """It has to be — the test suite and a fresh clone both depend on
        it, which is exactly why the startup guard below exists."""
        assert resolve_auth_mode(get_settings()) is AuthMode.LOCAL

    def test_unknown_mode_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(get_settings(), "auth_mode", "kerberos")
        with pytest.raises(AuthModeConfigurationError):
            resolve_auth_mode(get_settings())

    @pytest.mark.parametrize("environment", ["local", "test", "ci"])
    def test_local_mode_is_allowed_in_development_environments(
        self, monkeypatch: pytest.MonkeyPatch, environment: str
    ) -> None:
        settings = get_settings()
        monkeypatch.setattr(settings, "auth_mode", "local")
        monkeypatch.setattr(settings, "environment", environment)
        assert validate_auth_configuration(settings) is AuthMode.LOCAL

    @pytest.mark.parametrize("environment", ["production", "staging", "demo"])
    def test_local_mode_refuses_to_start_anywhere_else(
        self, monkeypatch: pytest.MonkeyPatch, environment: str
    ) -> None:
        """The ADR-0015 obligation. A deployment that forgets AUTH_MODE
        silently inherits self-issued tokens and every login still works —
        there is no runtime symptom, so refusing to boot is the only signal
        that cannot be missed."""
        settings = get_settings()
        monkeypatch.setattr(settings, "auth_mode", "local")
        monkeypatch.setattr(settings, "environment", environment)
        with pytest.raises(AuthModeConfigurationError, match="not permitted"):
            validate_auth_configuration(settings)

    def test_unknown_environment_names_default_to_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Allowlist, not denylist — an environment name nobody anticipated
        must inherit the safe behavior."""
        settings = get_settings()
        monkeypatch.setattr(settings, "auth_mode", "local")
        monkeypatch.setattr(settings, "environment", "uat-eu-west")
        with pytest.raises(AuthModeConfigurationError):
            validate_auth_configuration(settings)

    def test_oidc_mode_requires_its_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Checked at boot, not at first login. A missing issuer found by a
        user is an outage; found at startup it is a container that never
        takes traffic."""
        settings = get_settings()
        monkeypatch.setattr(settings, "auth_mode", "oidc")
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "oidc_issuer", "")
        with pytest.raises(AuthModeConfigurationError, match="OIDC_ISSUER"):
            validate_auth_configuration(settings)


class TestOIDCTokenValidation:
    def test_valid_token_is_accepted(
        self, oidc_validator: OIDCValidator, rsa_keys: dict[str, Any]
    ) -> None:
        token = _make_token(
            rsa_keys, subject="kc-1", email="a@cordant.io", roles=["meridian-hr"]
        )
        principal = oidc_validator.validate(token)
        assert principal.subject == "kc-1"
        assert principal.email == "a@cordant.io"
        assert "meridian-hr" in principal.realm_roles

    def test_token_from_another_realm_is_rejected(
        self, oidc_validator: OIDCValidator, rsa_keys: dict[str, Any]
    ) -> None:
        """Without issuer validation, a token from any Keycloak realm —
        including one an attacker runs — would be accepted."""
        token = _make_token(
            rsa_keys,
            subject="kc-1",
            email="a@cordant.io",
            roles=["meridian-hr"],
            issuer="http://evil:8080/realms/other",
        )
        with pytest.raises(InvalidTokenError):
            oidc_validator.validate(token)

    def test_token_for_another_client_is_rejected(
        self, oidc_validator: OIDCValidator, rsa_keys: dict[str, Any]
    ) -> None:
        """Token substitution: a token minted for a different client in the
        same realm must not work here. This is the check most often skipped,
        because Keycloak only populates `aud` with an audience mapper
        configured."""
        token = _make_token(
            rsa_keys,
            subject="kc-1",
            email="a@cordant.io",
            roles=["meridian-hr"],
            audience="some-other-client",
        )
        with pytest.raises(InvalidTokenError):
            oidc_validator.validate(token)

    def test_expired_token_is_rejected(
        self, oidc_validator: OIDCValidator, rsa_keys: dict[str, Any]
    ) -> None:
        token = _make_token(
            rsa_keys,
            subject="kc-1",
            email="a@cordant.io",
            roles=["meridian-hr"],
            expires_in=-3600,
        )
        with pytest.raises(InvalidTokenError):
            oidc_validator.validate(token)

    def test_token_signed_by_an_unknown_key_is_rejected(
        self, oidc_validator: OIDCValidator, rsa_keys: dict[str, Any]
    ) -> None:
        token = _make_token(
            rsa_keys,
            subject="kc-1",
            email="a@cordant.io",
            roles=["meridian-hr"],
            kid="some-other-key",
        )
        with pytest.raises(InvalidTokenError):
            oidc_validator.validate(token)

    def test_hs256_token_is_rejected_before_verification(
        self, oidc_validator: OIDCValidator
    ) -> None:
        """Algorithm confusion: an attacker signs with the *public* key as
        an HMAC secret and a verifier that trusts the header's alg accepts
        it. HS256 must never reach the verifier."""
        forged = jwt.encode(
            {"sub": "kc-1", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300},
            "public-key-as-hmac-secret",
            algorithm="HS256",
            headers={"kid": KID},
        )
        with pytest.raises(InvalidTokenError, match="Unsupported token algorithm"):
            oidc_validator.validate(forged)

    def test_token_without_a_key_id_is_rejected(self, oidc_validator: OIDCValidator) -> None:
        unsigned = jwt.encode(
            {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300},
            "secret",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            oidc_validator.validate(unsigned)

    def test_rejection_reason_is_not_disclosed_to_the_caller(
        self, oidc_validator: OIDCValidator, rsa_keys: dict[str, Any]
    ) -> None:
        """Telling a caller "audience mismatch" rather than "invalid token"
        hands them a way to iterate toward a token that works."""
        token = _make_token(
            rsa_keys,
            subject="kc-1",
            email="a@cordant.io",
            roles=["meridian-hr"],
            audience="wrong",
        )
        with pytest.raises(InvalidTokenError) as exc_info:
            oidc_validator.validate(token)
        assert "audience" not in str(exc_info.value).lower()


class TestRoleMapping:
    @pytest.mark.parametrize(
        ("keycloak_role", "expected"),
        [
            ("meridian-employee", UserRole.EMPLOYEE),
            ("meridian-manager", UserRole.MANAGER),
            ("meridian-hr", UserRole.HR),
            ("meridian-it", UserRole.IT),
            ("meridian-security", UserRole.SECURITY),
            ("meridian-administrator", UserRole.ADMINISTRATOR),
        ],
    )
    def test_every_role_maps(self, keycloak_role: str, expected: UserRole) -> None:
        principal = OIDCPrincipal(
            subject="s",
            email="e@cordant.io",
            full_name="n",
            realm_roles=(keycloak_role,),
            client_roles=(),
        )
        assert oidc_resolver.map_roles(principal) is expected

    def test_keycloak_builtin_roles_are_ignored(self) -> None:
        """Every Keycloak user carries offline_access and friends; none of
        them mean anything here."""
        principal = OIDCPrincipal(
            subject="s",
            email="e@cordant.io",
            full_name="n",
            realm_roles=("offline_access", "uma_authorization", "default-roles-meridian"),
            client_roles=(),
        )
        assert oidc_resolver.map_roles(principal) is None

    def test_highest_role_wins(self) -> None:
        """A user who is both manager and administrator gets administrator,
        not whichever came first in an unordered set."""
        principal = OIDCPrincipal(
            subject="s",
            email="e@cordant.io",
            full_name="n",
            realm_roles=("meridian-manager", "meridian-administrator", "meridian-employee"),
            client_roles=(),
        )
        assert oidc_resolver.map_roles(principal) is UserRole.ADMINISTRATOR

    def test_client_roles_are_read_too(self) -> None:
        principal = OIDCPrincipal(
            subject="s",
            email="e@cordant.io",
            full_name="n",
            realm_roles=(),
            client_roles=("meridian-it",),
        )
        assert oidc_resolver.map_roles(principal) is UserRole.IT

    def test_no_meridian_role_returns_none_rather_than_defaulting(self) -> None:
        """Defaulting to EMPLOYEE would silently give every Keycloak user in
        the realm a working Meridian account."""
        principal = OIDCPrincipal(
            subject="s", email="e@cordant.io", full_name="n", realm_roles=(), client_roles=()
        )
        assert oidc_resolver.map_roles(principal) is None


class TestUserResolution:
    def test_resolves_by_external_identity(
        self, db_session: Session, oidc_settings: Any
    ) -> None:
        user = _create_user(db_session, email="link1@cordant.io", role=UserRole.HR)
        _link_keycloak_subject(db_session, user, "kc-link-1")
        principal = OIDCPrincipal(
            subject="kc-link-1",
            email="different@cordant.io",
            full_name="n",
            realm_roles=("meridian-hr",),
            client_roles=(),
        )
        assert oidc_resolver.resolve_user(db_session, principal).id == user.id

    def test_first_login_links_by_email_then_persists_the_mapping(
        self, db_session: Session, oidc_settings: Any
    ) -> None:
        """Email is the fallback for a seeded or SCIM-provisioned user whose
        mapping does not exist yet; the first match writes it so later
        logins take the stable path."""
        user = _create_user(db_session, email="link2@cordant.io", role=UserRole.IT)
        principal = OIDCPrincipal(
            subject="kc-link-2",
            email="link2@cordant.io",
            full_name="n",
            realm_roles=("meridian-it",),
            client_roles=(),
        )
        assert oidc_resolver.resolve_user(db_session, principal).id == user.id

        identity = (
            db_session.query(ExternalIdentity)
            .filter(ExternalIdentity.external_id == "kc-link-2")
            .one()
        )
        assert identity.entity_id == user.id

    def test_email_matching_is_case_insensitive(
        self, db_session: Session, oidc_settings: Any
    ) -> None:
        user = _create_user(db_session, email="mixedcase@cordant.io", role=UserRole.HR)
        principal = OIDCPrincipal(
            subject="kc-case-1",
            email="MixedCase@Cordant.IO",
            full_name="n",
            realm_roles=("meridian-hr",),
            client_roles=(),
        )
        assert oidc_resolver.resolve_user(db_session, principal).id == user.id

    def test_unprovisioned_identity_is_rejected_not_created(
        self, db_session: Session, oidc_settings: Any
    ) -> None:
        """OIDC authenticates; SCIM provisions. Just-in-time creation on
        login would make SCIM decorative and leave account creation with no
        audit trail."""
        before = db_session.query(User).count()
        principal = OIDCPrincipal(
            subject="kc-stranger",
            email="stranger@elsewhere.com",
            full_name="n",
            realm_roles=("meridian-hr",),
            client_roles=(),
        )
        with pytest.raises(InvalidTokenError):
            oidc_resolver.resolve_user(db_session, principal)
        assert db_session.query(User).count() == before

    def test_deactivated_user_is_refused(
        self, db_session: Session, oidc_settings: Any
    ) -> None:
        """A token issued before deprovisioning stays cryptographically
        valid until it expires, so the IdP alone cannot revoke access
        promptly — the resource server has to check too."""
        from app.core.exceptions import PermissionDeniedError

        user = _create_user(db_session, email="gone@cordant.io", role=UserRole.HR)
        user.is_active = False
        db_session.commit()
        _link_keycloak_subject(db_session, user, "kc-gone")

        principal = OIDCPrincipal(
            subject="kc-gone",
            email="gone@cordant.io",
            full_name="n",
            realm_roles=("meridian-hr",),
            client_roles=(),
        )
        with pytest.raises(PermissionDeniedError):
            oidc_resolver.resolve_user(db_session, principal)


class TestRbacParity:
    """The test that justifies dual-mode auth existing at all.

    Same endpoints, same roles, same expected outcomes — asserted through
    local JWT and through OIDC. If the two paths ever diverge on
    authorization, this is what catches it.
    """

    ENDPOINTS = ("/integrations/connections", "/inbound/events", "/employees")

    def _local_headers(self, client: TestClient, db: Session, role: UserRole) -> dict[str, str]:
        email = f"parity-local-{role.value}-{uuid.uuid4().hex[:6]}@cordant.io"
        _create_user(db, email=email, role=role)
        token = client.post(
            "/auth/login", json={"email": email, "password": TEST_PASSWORD}
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _oidc_headers(
        self, db: Session, rsa_keys: dict[str, Any], role: UserRole
    ) -> dict[str, str]:
        email = f"parity-oidc-{role.value}-{uuid.uuid4().hex[:6]}@cordant.io"
        subject = f"kc-{uuid.uuid4().hex[:8]}"
        user = _create_user(db, email=email, role=role)
        _link_keycloak_subject(db, user, subject)
        token = _make_token(
            rsa_keys, subject=subject, email=email, roles=[f"meridian-{role.value}"]
        )
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.parametrize("role", list(UserRole))
    def test_authorization_decisions_are_identical_in_both_modes(
        self,
        client: TestClient,
        db_session: Session,
        rsa_keys: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        oidc_settings: Any,
        role: UserRole,
    ) -> None:
        settings = get_settings()
        validator = OIDCValidator(settings, jwks_cache=_FakeJWKSCache(rsa_keys["public_jwk"]))
        monkeypatch.setattr(deps, "get_oidc_validator", lambda: validator)

        oidc_headers = self._oidc_headers(db_session, rsa_keys, role)
        oidc_results = {
            path: client.get(path, headers=oidc_headers).status_code for path in self.ENDPOINTS
        }

        monkeypatch.setattr(settings, "auth_mode", "local")
        local_headers = self._local_headers(client, db_session, role)
        local_results = {
            path: client.get(path, headers=local_headers).status_code for path in self.ENDPOINTS
        }

        assert oidc_results == local_results, (
            f"Authorization diverged between modes for {role.value}: "
            f"oidc={oidc_results} local={local_results}"
        )

    def test_a_token_from_the_wrong_mode_is_refused(
        self,
        client: TestClient,
        db_session: Session,
        rsa_keys: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        oidc_settings: Any,
    ) -> None:
        """A validator that accepted either kind would let an attacker
        choose which set of rules to be judged by."""
        settings = get_settings()
        validator = OIDCValidator(settings, jwks_cache=_FakeJWKSCache(rsa_keys["public_jwk"]))
        monkeypatch.setattr(deps, "get_oidc_validator", lambda: validator)

        monkeypatch.setattr(settings, "auth_mode", "local")
        local_headers = self._local_headers(client, db_session, UserRole.ADMINISTRATOR)

        monkeypatch.setattr(settings, "auth_mode", "oidc")
        assert client.get("/integrations/connections", headers=local_headers).status_code == 401
