"""Shared authentication helpers for the test suite.

Not a pytest fixture module on purpose: each test file keeps its own
`db_session`/`client` fixtures (per-file SQLite databases), so these are
plain functions that any test file can import and call against its own
`db_session`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.models import Farmer, ProcurementCentre, User, UserRole

DEFAULT_TEST_PASSWORD = "TestPass123!"


def create_user(
    session: Session,
    role: UserRole,
    *,
    email: str,
    farmer_id: int | None = None,
    centre_id: int | None = None,
    password: str = DEFAULT_TEST_PASSWORD,
) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=role,
        farmer_id=farmer_id,
        centre_id=centre_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def token_for(user: User) -> str:
    return create_access_token(user_id=user.id, role=user.role.value)


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user)}"}


def create_admin(session: Session, *, email: str = "admin@example.test") -> User:
    return create_user(session, UserRole.ADMIN, email=email)


def create_farmer_user(
    session: Session, farmer: Farmer, *, email: str | None = None
) -> User:
    return create_user(
        session,
        UserRole.FARMER,
        email=email or f"farmer{farmer.id}@example.test",
        farmer_id=farmer.id,
    )


def create_staff_user(
    session: Session, centre: ProcurementCentre, *, email: str | None = None
) -> User:
    return create_user(
        session,
        UserRole.CENTRE_STAFF,
        email=email or f"staff-centre{centre.id}@example.test",
        centre_id=centre.id,
    )
