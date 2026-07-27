from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.application import ApplicationResponse
from app.services.applications import service as application_service

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationResponse])
def list_applications(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[ApplicationResponse]:
    """The application catalog — visible to any authenticated user, same
    reasoning as the employee directory (`GET /employees`): you need to see
    what's requestable before you can request it. Write access isn't a V1
    concern; see ApplicationResponse's docstring."""
    return application_service.list_applications(db)
