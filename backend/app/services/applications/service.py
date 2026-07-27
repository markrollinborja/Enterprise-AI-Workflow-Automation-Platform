from sqlalchemy.orm import Session

from app.models.application import Application
from app.repositories import application_repo
from app.schemas.application import ApplicationResponse


def _to_response(application: Application) -> ApplicationResponse:
    return ApplicationResponse(
        id=application.id,
        name=application.name,
        description=application.description,
        risk_level=application.risk_level,
        created_at=application.created_at,
    )


def list_applications(db: Session) -> list[ApplicationResponse]:
    return [_to_response(a) for a in application_repo.list_all(db)]
