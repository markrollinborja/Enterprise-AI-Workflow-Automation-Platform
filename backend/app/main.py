import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    access_requests,
    applications,
    approvals,
    auth,
    dashboard,
    departments,
    employees,
    health,
    inbound_events,
    integrations,
    notifications,
    saml,
    scim,
    users,
    webhooks,
    workflow_instances,
)
from app.core.auth_mode import validate_auth_configuration
from app.core.config import get_settings
from app.core.correlation import (
    CORRELATION_ID_HEADER,
    ensure_correlation_id,
    get_correlation_id,
    set_correlation_id,
)
from app.core.exceptions import AppError
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

# Refuse to start rather than run with an unsafe auth configuration
# (ADR-0015). Deliberately at import, before the app object exists: the
# failure this prevents — a deployment silently inheriting local JWT auth
# because AUTH_MODE was never set — has no visible symptom at runtime, since
# every login still works. A container that will not boot is the only signal
# that cannot be missed.
_auth_mode = validate_auth_configuration(settings)
logging.getLogger(__name__).info(
    "Authentication configured", extra={"auth_mode": _auth_mode.value}
)

app = FastAPI(title=settings.app_name, version="0.1.0")

# Local-dev-only CORS: frontend runs on a different port under Vite.
# Tightened before anything resembling production use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Bind a correlation ID to this request, then echo it back.

    Registered before anything else runs so that every log line produced
    while handling the request — including the AppError handler below —
    already carries the ID. Echoing it on the response matters as much as
    consuming it: n8n and the support console record what they were told,
    which is what lets a human paste one string into the console's search
    box and find the whole transaction (Module 8).

    Deliberately not inside a try/finally that resets the value: each
    request runs in its own asyncio task with its own ContextVar copy, so
    there is nothing to leak into the next request.
    """
    correlation_id = ensure_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    set_correlation_id(correlation_id)
    response = await call_next(request)
    response.headers[CORRELATION_ID_HEADER] = correlation_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Single translation point from domain errors to HTTP responses — see
    app.core.exceptions for why services raise AppError, not HTTPException."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "type": type(exc).__name__,
                "message": exc.message,
                # So a user who hits an error can quote one string to
                # support, and support can find every log line, provider
                # call, and workflow step behind it. Additive — existing
                # clients reading .error.type/.message are unaffected.
                "correlation_id": get_correlation_id(),
            }
        },
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(departments.router)
app.include_router(employees.router)
app.include_router(approvals.router)
app.include_router(applications.router)
app.include_router(access_requests.router)
app.include_router(webhooks.router)
app.include_router(notifications.router)
app.include_router(dashboard.router)
app.include_router(workflow_instances.router)
app.include_router(integrations.router)
app.include_router(inbound_events.router)
app.include_router(scim.router)
app.include_router(saml.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "running"}
