"""SAML PoC routes (V2 Module 4 remainder, ADR-0021).

Two endpoints, deliberately outside AUTH_MODE's dispatch
(app/api/deps.py): `GET /auth/saml/login` starts an SP-initiated login by
redirecting the browser to Keycloak's SAML SSO endpoint; `POST
/auth/saml/acs` is the Assertion Consumer Service Keycloak posts the signed
response back to. A successful ACS call issues the same local-JWT format
AUTH_MODE=local validates and redirects the browser to the frontend
carrying it — this route pair works regardless of which AUTH_MODE a
deployment runs, because it was never meant to compete with OIDC as the
primary sign-in path (see ADR-0021).
"""

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import IdentityProviderUnavailableError
from app.core.config import get_settings
from app.core.saml import SAMLUnavailableError, SAMLValidator
from app.db.session import get_db
from app.services.auth import saml_resolver
from app.services.auth.service import issue_token_for

router = APIRouter(prefix="/auth/saml", tags=["auth"])

# Built once, not per request — the validator owns the pending-request
# store (AuthnRequest ids awaiting their matching response) and the IdP
# metadata cache. A fresh instance per request would forget every id it
# issued before the response arrived, failing every login on the
# InResponseTo check, and would refetch Keycloak's signing certificate on
# every single login attempt.
_validator: SAMLValidator | None = None


def get_saml_validator() -> SAMLValidator:
    global _validator
    if _validator is None:
        _validator = SAMLValidator(get_settings())
    return _validator


def reset_saml_validator() -> None:
    """Drop the cached validator. For tests that inject a fake metadata
    cache or pending-request store."""
    global _validator
    _validator = None


@router.get("/login")
def saml_login() -> RedirectResponse:
    try:
        redirect_url = get_saml_validator().start_login()
    except SAMLUnavailableError as exc:
        raise IdentityProviderUnavailableError(
            "Identity provider is unavailable; try again shortly"
        ) from exc
    return RedirectResponse(redirect_url, status_code=302)


@router.post("/acs")
def saml_acs(
    SAMLResponse: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Keycloak POSTs here (HTTP-POST binding) with the signed assertion as
    a form field, not JSON — the field name is dictated by the SAML spec,
    not this codebase's naming conventions."""
    try:
        principal = get_saml_validator().validate_response(SAMLResponse)
    except SAMLUnavailableError as exc:
        raise IdentityProviderUnavailableError(
            "Identity provider is unavailable; try again shortly"
        ) from exc

    user = saml_resolver.resolve_user(db, principal)
    token = issue_token_for(user)

    redirect_url = f"{get_settings().saml_frontend_redirect_url}?token={token}"
    return RedirectResponse(redirect_url, status_code=302)
