from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import ensure_booking_access, get_current_user
from app.db.session import get_db
from app.models import User, UserRole
from app.repositories import bookings as booking_repository
from app.schemas.procurement import BookingCreate, BookingResponse
from app.services.bookings import BookingError, create_booking as create_booking_service


router = APIRouter()


@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    booking_data: BookingCreate,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingResponse:
    # A FARMER may only ever create a booking for themselves - the payload's
    # farmer_id must match the caller's own linked farmer profile, even
    # though the field is still present in the request body (the booking
    # domain keys off it, and ADMIN legitimately books on a farmer's
    # behalf, e.g. over a phone call).
    if current_user.role == UserRole.FARMER and current_user.farmer_id != booking_data.farmer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only create bookings for your own farmer profile",
        )
    if current_user.role == UserRole.CENTRE_STAFF:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Centre staff cannot create bookings",
        )
    try:
        return create_booking_service(session, booking_data)
    except BookingError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BookingResponse:
    booking = booking_repository.get_booking(session, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    ensure_booking_access(current_user, farmer_id=booking.farmer_id, centre_id=booking.centre_id)
    return booking
