"""Authentication mode selection and its startup guard.

ADR-0015 chose dual-mode auth — local JWT for hermetic tests, Keycloak OIDC
for the real flow — and recorded one obligation with it: `AUTH_MODE=local`
must be impossible to reach in a deployed environment. This module is that
obligation, made executable.

The failure this prevents is specific and entirely plausible. `local` is the
default, because it has to be for the test suite and for anyone who just
cloned the repo. A deployment that forgets to set `AUTH_MODE` therefore
inherits self-issued tokens signed with whatever `JWT_SECRET_KEY` happens to
be set, silently, with no error and no visible symptom — every login still
works. Nothing about the running system would look wrong. A startup refusal
converts that from an invisible security downgrade into a container that
will not boot.
"""

import enum

from app.core.config import Settings


class AuthMode(str, enum.Enum):
    LOCAL = "local"
    OIDC = "oidc"


class AuthModeConfigurationError(RuntimeError):
    """Raised at startup, never at request time.

    Deliberately a RuntimeError rather than an AppError: an AppError becomes
    an HTTP response, and there is no request to respond to here. This must
    kill the process.
    """


# Environments where self-issued tokens are legitimate. Anything else is
# treated as "somewhere it matters" — an allowlist rather than a denylist,
# so a new environment name added later defaults to the strict behavior
# instead of silently inheriting the permissive one.
_LOCAL_ENVIRONMENTS = frozenset({"local", "test", "ci"})


def resolve_auth_mode(settings: Settings) -> AuthMode:
    raw = (settings.auth_mode or "").strip().lower()
    try:
        return AuthMode(raw)
    except ValueError as exc:
        raise AuthModeConfigurationError(
            f"AUTH_MODE must be one of {[m.value for m in AuthMode]}, got '{settings.auth_mode}'"
        ) from exc


def validate_auth_configuration(settings: Settings) -> AuthMode:
    """Resolve the mode and refuse to start if the combination is unsafe.

    Called once from app.main at import. Returns the mode so the caller can
    log it — a deployment should be able to see which mode it came up in
    without inferring it from behavior.
    """
    mode = resolve_auth_mode(settings)
    environment = (settings.environment or "").strip().lower()

    if mode is AuthMode.LOCAL and environment not in _LOCAL_ENVIRONMENTS:
        raise AuthModeConfigurationError(
            f"AUTH_MODE=local is not permitted when ENVIRONMENT='{settings.environment}'. "
            f"Local JWT auth is for tests and local development only (ADR-0015). "
            f"Set AUTH_MODE=oidc, or set ENVIRONMENT to one of {sorted(_LOCAL_ENVIRONMENTS)}."
        )

    if mode is AuthMode.OIDC:
        # Checked at startup rather than at first login. A missing issuer
        # discovered when the first user tries to sign in is an outage
        # found by a user; discovered at boot it is a container that never
        # takes traffic.
        missing = [
            name
            for name, value in (
                ("OIDC_ISSUER", settings.oidc_issuer),
                ("OIDC_CLIENT_ID", settings.oidc_client_id),
                ("OIDC_CLIENT_SECRET", settings.oidc_client_secret),
            )
            if not value
        ]
        if missing:
            raise AuthModeConfigurationError(
                f"AUTH_MODE=oidc requires {', '.join(missing)} to be set."
            )

    return mode
