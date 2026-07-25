from sqlalchemy.orm import Session

from app.core.exceptions import InvalidCredentialsError
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.repositories import user_repo


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    user = user_repo.get_by_email(db, email)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        # Deliberately the same error for "no such user" and "wrong password" —
        # distinguishing them would let a caller enumerate valid emails.
        raise InvalidCredentialsError("Incorrect email or password")
    return user


def issue_token_for(user: User) -> str:
    return create_access_token(subject=user.id, role=user.role.value)
