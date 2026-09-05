from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import User
from app.schemas.auth import Token, UserRegister, UserResponse
from app.services import auth as auth_service

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegister,
    session: Session = Depends(get_db),
) -> UserResponse:
    """Public, unauthenticated self-registration. FARMER only.

    CENTRE_STAFF and ADMIN cannot be self-registered here (enforced by the
    request schema's role validator) - both are privileged roles and must
    be provisioned by an existing ADMIN via POST /api/admin/users instead.
    """
    try:
        return auth_service.register_user(session, payload)
    except auth_service.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_db),
) -> Token:
    """OAuth2-compatible password login. `username` is the account email."""
    try:
        user = auth_service.authenticate_user(session, form_data.username, form_data.password)
    except auth_service.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    token = create_access_token(user_id=user.id, role=user.role.value)
    return Token(access_token=token)


@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)) -> UserResponse:
    return current_user
