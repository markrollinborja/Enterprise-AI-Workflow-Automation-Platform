"""Seed demo users for local development and interview demos.

Fictional company: Cordant Industries. One user per role, per
docs/architecture/authentication.md. Idempotent — safe to run repeatedly,
only creates users that don't already exist (matched by email).

Demo password is intentionally simple and documented here in plain sight —
this is a local-dev-only credential, never a real one, never used outside
`docker compose up` / a portfolio demo.
"""

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.enums import UserRole
from app.repositories import user_repo

DEMO_PASSWORD = "MeridianDemo123!"

DEMO_USERS = [
    {"email": "priya.anand@cordant.io", "full_name": "Priya Anand", "role": UserRole.HR},
    {"email": "daniel.osei@cordant.io", "full_name": "Daniel Osei", "role": UserRole.MANAGER},
    {"email": "sam.whitfield@cordant.io", "full_name": "Sam Whitfield", "role": UserRole.IT},
    {"email": "renee.castillo@cordant.io", "full_name": "Renee Castillo", "role": UserRole.SECURITY},
    {"email": "jordan.lee@cordant.io", "full_name": "Jordan Lee", "role": UserRole.EMPLOYEE},
    {
        "email": "ava.thompson@cordant.io",
        "full_name": "Ava Thompson",
        "role": UserRole.ADMINISTRATOR,
    },
]


def seed_demo_users() -> None:
    db = SessionLocal()
    try:
        created = 0
        for demo in DEMO_USERS:
            if user_repo.get_by_email(db, demo["email"]) is not None:
                continue
            user_repo.create(
                db,
                email=demo["email"],
                hashed_password=hash_password(DEMO_PASSWORD),
                full_name=demo["full_name"],
                role=demo["role"],
            )
            created += 1
        skipped = len(DEMO_USERS) - created
        print(f"Seed complete: {created} user(s) created, {skipped} already existed.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo_users()
