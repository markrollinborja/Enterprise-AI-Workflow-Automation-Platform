from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import user_repo
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.ADMINISTRATOR)),
) -> list[User]:
    """Administrator-only — demonstrates require_role enforcing a real
    resource, not just a throwaway test route."""
    return user_repo.list_all(db)
