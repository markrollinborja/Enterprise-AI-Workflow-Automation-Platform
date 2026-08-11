from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.auth_mode import AuthMode, resolve_auth_mode
from app.core.config import get_settings
from app.core.exceptions import AuthModeMismatchError
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import AuthModeResponse, LoginRequest, TokenResponse, UserResponse
from app.services.auth import service as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/mode", response_model=AuthModeResponse)
def auth_mode() -> AuthModeResponse:
    """Public and unauthenticated on purpose — the login screen has to call
    this *before* a user has any credentials to offer, to know whether to
    show a password form or a "sign in with Keycloak" redirect. Returns
    nothing that isn't already implied by which login screen a given
    deployment would show anyway."""
    return AuthModeResponse(mode=resolve_auth_mode(get_settings()).value)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if resolve_auth_mode(get_settings()) is not AuthMode.LOCAL:
        # A local token minted here would validate against neither checker
        # (get_current_user runs exactly one, per ADR-0015) — refusing at
        # issuance is clearer than handing back a token that looks like a
        # successful login and then 401s on every request that uses it.
        raise AuthModeMismatchError(
            "Password login is disabled; this deployment authenticates through OIDC."
        )
    user = auth_service.authenticate_user(db, email=payload.email, password=payload.password)
    token = auth_service.issue_token_for(user)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
