from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import Farmer, ProcurementCentre, User, UserRole
from app.repositories import users as user_repository
from app.schemas.auth import AdminUserCreate, UserRegister


@dataclass
class AuthError(Exception):
    detail: str
    status_code: int


def _resolve_role_resource(
    session: Session, *, role: UserRole, farmer_id: int | None, centre_id: int | None
) -> tuple[int | None, int | None]:
    """Validate the role/resource pairing and confirm the referenced
    farmer/centre exists. Returns the (farmer_id, centre_id) to store.

    Shared by both public self-registration and admin provisioning so the
    invariant - FARMER needs exactly a farmer_id, CENTRE_STAFF needs
    exactly a centre_id, ADMIN needs neither - is enforced identically and
    in exactly one place, regardless of which endpoint created the user.
    """
    if role == UserRole.FARMER:
        if farmer_id is None:
            raise AuthError("farmer_id is required when registering as FARMER", 422)
        if centre_id is not None:
            raise AuthError("centre_id is not valid when registering as FARMER", 422)
        farmer = session.get(Farmer, farmer_id)
        if farmer is None:
            raise AuthError("Farmer not found", 404)
        if user_repository.get_user_by_farmer_id(session, farmer_id) is not None:
            raise AuthError("This farmer already has an account", 409)
        return farmer_id, None

    if role == UserRole.CENTRE_STAFF:
        if centre_id is None:
            raise AuthError("centre_id is required when registering as CENTRE_STAFF", 422)
        if farmer_id is not None:
            raise AuthError("farmer_id is not valid when registering as CENTRE_STAFF", 422)
        centre = session.get(ProcurementCentre, centre_id)
        if centre is None:
            raise AuthError("Procurement centre not found", 404)
        return None, centre_id

    # UserRole.ADMIN
    if farmer_id is not None:
        raise AuthError("farmer_id is not valid when provisioning ADMIN", 422)
    if centre_id is not None:
        raise AuthError("centre_id is not valid when provisioning ADMIN", 422)
    return None, None


def _create_user(
    session: Session,
    *,
    email: str,
    password: str,
    role: UserRole,
    farmer_id: int | None,
    centre_id: int | None,
) -> User:
    if user_repository.get_user_by_email(session, email) is not None:
        raise AuthError("An account with this email already exists", 409)

    resolved_farmer_id, resolved_centre_id = _resolve_role_resource(
        session, role=role, farmer_id=farmer_id, centre_id=centre_id
    )

    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=role,
        farmer_id=resolved_farmer_id,
        centre_id=resolved_centre_id,
    )
    return user_repository.create_user(session, user)


def register_user(session: Session, data: UserRegister) -> User:
    """Public, unauthenticated self-registration. The schema itself
    restricts `data.role` to `SELF_REGISTERABLE_ROLES` (FARMER only); this
    function does not re-check that, so it must never be called with
    unvalidated input from another source.
    """
    return _create_user(
        session,
        email=data.email,
        password=data.password,
        role=data.role,
        farmer_id=data.farmer_id,
        centre_id=data.centre_id,
    )


def provision_user(session: Session, data: AdminUserCreate) -> User:
    """ADMIN-only account provisioning. Callers must independently ensure
    the caller is an authenticated ADMIN (enforced by `require_admin` at
    the router level) before calling this - it does not check that itself.
    """
    return _create_user(
        session,
        email=data.email,
        password=data.password,
        role=data.role,
        farmer_id=data.farmer_id,
        centre_id=data.centre_id,
    )


def authenticate_user(session: Session, email: str, password: str) -> User:
    user = user_repository.get_user_by_email(session, email.lower())
    # Deliberately identical error for "no such user" and "wrong password":
    # distinguishing them would let a caller enumerate registered emails.
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise AuthError("Incorrect email or password", 401)
    return user
