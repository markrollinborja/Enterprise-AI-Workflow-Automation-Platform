from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError

settings = get_settings()

# Calling bcrypt directly, not through passlib's CryptContext. passlib 1.7.4
# (its last release, 2020, effectively unmaintained) probes bcrypt.__about__
# to detect the backend version — an attribute modern bcrypt (>=4.1) no
# longer has, which breaks passlib's hashing entirely. bcrypt's own hashpw/
# checkpw/gensalt API is stable and doesn't need that shim, and we only ever
# use one hashing scheme, so CryptContext's multi-scheme abstraction wasn't
# buying us anything anyway.


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(*, subject: UUID, role: str) -> str:
    """Issue an 8-hour JWT (see docs/architecture/authentication.md for why
    8 hours and why no refresh token in V1)."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(subject), "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@dataclass
class TokenPayload:
    user_id: UUID
    role: str


def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError("Invalid or expired token") from exc
    return TokenPayload(user_id=UUID(payload["sub"]), role=payload["role"])
