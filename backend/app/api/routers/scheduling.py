from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import (
    ensure_booking_access,
    ensure_centre_scope,
    get_current_user,
    require_centre_staff_or_admin,
)
from app.db.session import get_db
from app.models import User
from app.repositories import bookings as booking_repository
from app.schemas.scheduling import SchedulingAssessmentResponse
from app.services import scheduling as scheduling_service

router = APIRouter()


def _raise_scheduling_error(error: scheduling_service.SchedulingError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("/bookings/{booking_id}", response_model=SchedulingAssessmentResponse)
async def get_booking_assessment(
    booking_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SchedulingAssessmentResponse:
    booking = booking_repository.get_booking(session, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    ensure_booking_access(current_user, farmer_id=booking.farmer_id, centre_id=booking.centre_id)
    try:
        return scheduling_service.assess_booking(session, booking_id)
    except scheduling_service.SchedulingError as error:
        _raise_scheduling_error(error)


@router.get("/centres/{centre_id}", response_model=list[SchedulingAssessmentResponse])
async def get_centre_assessments(
    centre_id: int,
    session: Session = Depends(get_db),
    current_user: User = Depends(require_centre_staff_or_admin),
) -> list[SchedulingAssessmentResponse]:
    # Aggregate, cross-farmer operational data - centre staff/admin only,
    # same as the live queue view.
    ensure_centre_scope(current_user, centre_id)
    try:
        return scheduling_service.assess_centre(session, centre_id)
    except scheduling_service.SchedulingError as error:
        _raise_scheduling_error(error)
