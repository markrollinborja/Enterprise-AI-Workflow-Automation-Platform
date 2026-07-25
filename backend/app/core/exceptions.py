class AppError(Exception):
    """Base class for application-specific errors.

    Subclasses set `status_code`; a single FastAPI exception handler (see
    app.main) translates any AppError into a consistent JSON error shape:
    `{"error": {"type": ..., "message": ...}}`. Services, repositories, and
    dependencies should raise a domain-shaped AppError, never HTTPException
    directly — that keeps HTTP concerns at the edge of the app instead of
    scattered through business logic, and guarantees every error response
    looks the same regardless of which layer raised it.
    """

    status_code = 400

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidCredentialsError(AppError):
    status_code = 401


class InvalidTokenError(AppError):
    status_code = 401


class PermissionDeniedError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404
