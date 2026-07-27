from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.access_request import AccessRequestCreate, AccessRequestResponse
from app.services.access_requests import service as access_request_service

router = APIRouter(prefix="/access-requests", tags=["access-requests"])


@router.post("", response_model=AccessRequestResponse)
def submit_access_request(
    payload: AccessRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AccessRequestResponse:
    """Any authenticated user with a linked employee record can submit —
    not role-restricted to UserRole.EMPLOYEE, since a manager or HR
    coordinator is also a person who might need to request their own
    software access."""
    return access_request_service.submit_access_request(db, payload, current_user=current_user)
