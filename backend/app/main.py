from fastapi import FastAPI, Request
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
    notifications,
    users,
    webhooks,
    workflow_instances,
)
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

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


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Single translation point from domain errors to HTTP responses — see
    app.core.exceptions for why services raise AppError, not HTTPException."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": type(exc).__name__, "message": exc.message}},
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


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "running"}
