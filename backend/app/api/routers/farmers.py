from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, UserRole
from app.repositories import farmers as farmer_repository
from app.schemas.procurement import FarmerCreate, FarmerResponse

router = APIRouter()


@router.post("/", response_model=FarmerResponse, status_code=status.HTTP_201_CREATED)
async def create_farmer(
    farmer_data: FarmerCreate,
    session: Session = Depends(get_db),
) -> FarmerResponse:
    return farmer_repository.create_farmer(session, farmer_data)


@router.get("/{farmer_id}", response_model=FarmerResponse)
async def get_farmer(
    farmer_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FarmerResponse:
    """Fetch a single farmer's profile (name/phone/village).

    Needed so a FARMER user logging in on a new device (where the
    onboarding-time localStorage copy of their profile is gone) can
    rehydrate their profile from just the `farmer_id` in their JWT.
    Resource-scoped like every other farmer-owned resource: a FARMER may
    only fetch their own linked profile, ADMIN may fetch any, and
    CENTRE_STAFF has no legitimate reason to browse farmer profiles
    outside of a booking/queue context (where they already go through
    `ensure_booking_access` instead).
    """
    if current_user.role == UserRole.FARMER and current_user.farmer_id != farmer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own farmer profile",
        )
    if current_user.role == UserRole.CENTRE_STAFF:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this resource",
        )
    farmer = farmer_repository.get_farmer(session, farmer_id)
    if farmer is None:
        raise HTTPException(status_code=404, detail="Farmer not found")
    return farmer
