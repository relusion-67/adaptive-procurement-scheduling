"""Reusable authentication/authorization dependencies for routers.

Centralizing these here (rather than duplicating checks per-router) is
what makes the RBAC model auditable: every endpoint that needs protection
composes `get_current_user`, `require_role`, or one of the resource-scope
helpers below instead of hand-rolling its own check.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import User, UserRole

# `tokenUrl` points Swagger/OpenAPI's "Authorize" button at the login
# endpoint; it does not change how tokens already in an Authorization
# header are validated. `auto_error=False` lets us raise our own 401 with
# a consistent body instead of FastAPI's default.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_prefix}/auth/login",
    auto_error=False,
)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: Session = Depends(get_db),
) -> User:
    """Resolve the caller's identity from a bearer JWT.

    Fails with 401 for: no token, a malformed token, an expired token, a
    token with an invalid signature, or a token referencing a user that no
    longer exists/is inactive. All of these fail identically on purpose
    (see `TokenError`'s docstring).
    """
    if token is None:
        raise _UNAUTHENTICATED

    try:
        payload = decode_access_token(token)
    except TokenError as error:
        raise _UNAUTHENTICATED from error

    user = session.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    # If the user's role changed since the token was issued, the token's
    # embedded role claim is stale; re-derive authorization from the
    # database rather than trusting the token's snapshot.
    return user


def require_role(*roles: UserRole):
    """Dependency factory: 403s unless `current_user.role` is one of
    `roles`. Use for endpoint-level RBAC (e.g. admin-only endpoints).
    """
    allowed: tuple[UserRole, ...] = roles

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this operation",
            )
        return current_user

    return _checker


require_admin = require_role(UserRole.ADMIN)
require_centre_staff_or_admin = require_role(UserRole.CENTRE_STAFF, UserRole.ADMIN)


def ensure_centre_scope(current_user: User, centre_id: int) -> None:
    """Enforce that CENTRE_STAFF users only operate on their own centre.

    ADMIN bypasses centre scoping entirely. Call this *after* a
    `require_centre_staff_or_admin` (or equivalent) dependency has already
    confirmed the caller's role; this only narrows staff to their own
    centre, it does not authenticate.
    """
    if current_user.role == UserRole.ADMIN:
        return
    if current_user.role == UserRole.CENTRE_STAFF and current_user.centre_id == centre_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not authorized for this procurement centre",
    )


def ensure_booking_access(current_user: User, *, farmer_id: int, centre_id: int) -> None:
    """Prevent IDOR on booking-derived resources (bookings, queue entries,
    ETA, scheduling assessments): a farmer may only reach their own
    booking; centre staff only bookings at their own centre; admins may
    reach any booking.
    """
    if current_user.role == UserRole.ADMIN:
        return
    if current_user.role == UserRole.FARMER and current_user.farmer_id == farmer_id:
        return
    if current_user.role == UserRole.CENTRE_STAFF and current_user.centre_id == centre_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You are not authorized to access this resource",
    )

