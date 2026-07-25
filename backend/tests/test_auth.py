from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User

TEST_PASSWORD = "CorrectHorse123!"


def _create_user(
    db: Session,
    *,
    email: str,
    role: UserRole = UserRole.EMPLOYEE,
    password: str = TEST_PASSWORD,
) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name="Test User",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, email: str, password: str = TEST_PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_login_success(client: TestClient, db_session: Session) -> None:
    _create_user(db_session, email="login-ok@cordant.io")
    response = client.post(
        "/auth/login", json={"email": "login-ok@cordant.io", "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_wrong_password(client: TestClient, db_session: Session) -> None:
    _create_user(db_session, email="login-bad@cordant.io")
    response = client.post(
        "/auth/login", json={"email": "login-bad@cordant.io", "password": "WrongPassword"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "InvalidCredentialsError"


def test_login_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "nobody@cordant.io", "password": "whatever"}
    )
    # Same error/status as wrong-password — see auth service comment on why.
    assert response.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    response = client.get("/auth/me")
    # FastAPI's HTTPBearer(auto_error=True) returns 403 for a *missing*
    # Authorization header specifically — 401 is what InvalidTokenError
    # returns for a present-but-invalid token. Both are asserted below.
    assert response.status_code == 403


def test_me_with_invalid_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_me_with_valid_token(client: TestClient, db_session: Session) -> None:
    _create_user(db_session, email="me-ok@cordant.io")
    token = _login(client, "me-ok@cordant.io")
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "me-ok@cordant.io"


def test_users_list_requires_admin(client: TestClient, db_session: Session) -> None:
    _create_user(db_session, email="not-admin@cordant.io", role=UserRole.EMPLOYEE)
    token = _login(client, "not-admin@cordant.io")
    response = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "PermissionDeniedError"


def test_users_list_allows_admin(client: TestClient, db_session: Session) -> None:
    _create_user(db_session, email="admin@cordant.io", role=UserRole.ADMINISTRATOR)
    token = _login(client, "admin@cordant.io")
    response = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert any(u["email"] == "admin@cordant.io" for u in response.json())
