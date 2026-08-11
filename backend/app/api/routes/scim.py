"""SCIM 2.0 endpoints — `/scim/v2/Users`.

Authenticated with a static bearer token, not a user JWT. A SCIM client is a
service belonging to an identity provider; it has no user session and no
role. That means these routes bypass `require_role` entirely, which is
exactly why the token check is the first thing every one of them does, and
why the token lives in its own setting rather than being any existing
credential.

Errors are returned in SCIM's own envelope, not this app's `{"error": ...}`
shape. A connector parses `scimType` to decide what to do next — a
`uniqueness` response tells it to fetch the existing resource instead of
retrying the create forever — so emitting our house error format here would
make the endpoint unusable by any real client even though every status code
was correct.
"""

import logging
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.correlation import get_correlation_id
from app.core.exceptions import AppError, InvalidTokenError, NotFoundError
from app.db.session import get_db
from app.models.user import User
from app.schemas.scim import (
    ScimEmail,
    ScimError,
    ScimListResponse,
    ScimMeta,
    ScimName,
    ScimPatchRequest,
    ScimUserRequest,
    ScimUserResponse,
)
from app.services.scim import service as scim_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scim/v2", tags=["scim"])

SCIM_CONTENT_TYPE = "application/scim+json"


def require_scim_client(
    authorization: str | None = Header(default=None),
) -> str:
    """Authenticate the SCIM client.

    `compare_digest`, not `==`: string comparison short-circuits on the
    first differing byte, so equality leaks how much of a guessed token was
    correct through response timing. An unset token rejects everything
    rather than disabling the check — the same rule as the webhook secret,
    for the same reason.
    """
    settings = get_settings()
    expected = settings.scim_bearer_token

    if not expected or not authorization:
        raise InvalidTokenError("SCIM authentication failed")

    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(presented.strip(), expected):
        raise InvalidTokenError("SCIM authentication failed")

    return presented


def _to_response(user: User, request: Request | None = None) -> ScimUserResponse:
    location = None
    if request is not None:
        location = str(request.url_for("scim_get_user", user_id=user.id))

    return ScimUserResponse(
        id=user.id,
        userName=user.email,
        name=ScimName(formatted=user.full_name),
        emails=[ScimEmail(value=user.email, primary=True, type="work")],
        active=user.is_active,
        roles=[user.role.value],
        meta=ScimMeta(
            resourceType="User",
            created=user.created_at,
            lastModified=user.updated_at,
            location=location,
        ),
    )


def _scim_error(status: int, detail: str, scim_type: str | None = None) -> JSONResponse:
    payload = ScimError(status=str(status), scimType=scim_type, detail=detail)  # type: ignore[arg-type]
    return JSONResponse(
        status_code=status,
        media_type=SCIM_CONTENT_TYPE,
        content=payload.model_dump(by_alias=True, exclude_none=True),
    )


@router.post("/Users", status_code=201)
def scim_create_user(
    payload: ScimUserRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _client: str = Depends(require_scim_client),
) -> Any:
    """Provision a user. Idempotent on `externalId`."""
    try:
        user = scim_service.create_user(db, payload)
    except scim_service.ScimConflictError as exc:
        return _scim_error(409, exc.message, scim_type="uniqueness")
    except scim_service.ScimInvalidValueError as exc:
        return _scim_error(400, exc.message, scim_type="invalidValue")

    logger.info(
        "SCIM user provisioned",
        extra={"user_id": str(user.id), "correlation_id": get_correlation_id()},
    )
    response.media_type = SCIM_CONTENT_TYPE
    return _to_response(user, request)


@router.get("/Users/{user_id}", name="scim_get_user")
def scim_get_user(
    user_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    _client: str = Depends(require_scim_client),
) -> Any:
    try:
        user = scim_service.get_user(db, user_id)
    except NotFoundError as exc:
        return _scim_error(404, exc.message)
    return _to_response(user, request)


@router.get("/Users")
def scim_list_users(
    request: Request,
    filter: str | None = Query(default=None),  # noqa: A002 - SCIM names this parameter
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=0, le=200),
    db: Session = Depends(get_db),
    _client: str = Depends(require_scim_client),
) -> Any:
    """List or filter users.

    Only `userName eq "value"` is supported, and that is deliberate. It is
    the filter every provisioning connector actually issues — to check
    whether a user exists before creating them — and implementing a general
    SCIM filter parser would be a meaningful amount of code serving no real
    client. Anything else returns `invalidFilter` rather than quietly
    ignoring the filter and returning every user, which would look like
    success while leaking the whole directory.
    """
    from app.repositories import user_repo

    if filter:
        parsed = _parse_username_filter(filter)
        if parsed is None:
            return _scim_error(
                400,
                "Only filters of the form 'userName eq \"value\"' are supported",
                scim_type="invalidFilter",
            )
        match = scim_service.find_by_username(db, parsed)
        users = [match] if match else []
    else:
        users = user_repo.list_all(db)

    window = users[start_index - 1 : start_index - 1 + count] if count else []
    return ScimListResponse(
        totalResults=len(users),
        itemsPerPage=len(window),
        startIndex=start_index,
        Resources=[_to_response(u, request) for u in window],
    )


@router.patch("/Users/{user_id}")
def scim_patch_user(
    user_id: UUID,
    patch: ScimPatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    _client: str = Depends(require_scim_client),
) -> Any:
    """Update a user. `active: false` is the deprovisioning signal."""
    try:
        user = scim_service.get_user(db, user_id)
        user = scim_service.apply_patch(db, user, patch)
    except NotFoundError as exc:
        return _scim_error(404, exc.message)
    except scim_service.ScimInvalidValueError as exc:
        return _scim_error(400, exc.message, scim_type="invalidPath")

    return _to_response(user, request)


# response_model=None is required, not stylistic. FastAPI infers a response
# model from the `-> Any` return annotation, then asserts at import time that
# a 204 route declares no body — so without this the entire app fails to
# start, not just this route. The annotation stays `Any` because the handler
# genuinely returns either a 204 Response or a SCIM-shaped JSONResponse.
@router.delete(
    "/Users/{user_id}", status_code=204, response_class=Response, response_model=None
)
def scim_delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    _client: str = Depends(require_scim_client),
) -> Any:
    """Deprovision — implemented as deactivation, never a row delete.

    Returning 204 keeps well-behaved connectors happy while the account,
    and every approval and audit row naming it, survives. Deleting the user
    would orphan exactly the history you need when asking what a departed
    employee had access to.
    """
    try:
        user = scim_service.get_user(db, user_id)
    except NotFoundError as exc:
        return _scim_error(404, exc.message)

    scim_service.deactivate_user(db, user)
    return Response(status_code=204)


def _parse_username_filter(raw: str) -> str | None:
    """Parse `userName eq "value"`, case-insensitively on the attribute.

    Hand-rolled rather than a filter grammar: this is the only supported
    filter (see scim_list_users), and a parser for a language with one
    sentence in it is not a parser.
    """
    parts = raw.strip().split(None, 2)
    if len(parts) != 3:
        return None
    attribute, operator, value = parts
    if attribute.lower() != "username" or operator.lower() != "eq":
        return None
    return value.strip().strip('"').strip("'") or None


def scim_error_handler(exc: AppError) -> JSONResponse:
    """Available for wiring into main.py if SCIM errors ever escape a route.

    Not registered globally: the app-wide AppError handler must keep
    returning this project's own error shape for every non-SCIM route.
    """
    return _scim_error(exc.status_code, exc.message)
