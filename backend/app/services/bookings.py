from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus
from app.repositories import bookings as booking_repository
from app.repositories import farmers as farmer_repository
from app.repositories import procurement as procurement_repository
from app.schemas.procurement import BookingCreate


@dataclass
class BookingError(Exception):
    detail: str
    status_code: int


def create_booking(session: Session, booking_data: BookingCreate) -> Booking:
    farmer = farmer_repository.get_farmer(session, booking_data.farmer_id)
    if farmer is None:
        raise BookingError("Farmer not found", 404)

    centre = procurement_repository.get_centre(session, booking_data.centre_id)
    if centre is None:
        raise BookingError("Procurement centre not found", 404)
    if not centre.active:
        raise BookingError("Procurement centre is inactive", 409)

    slot = procurement_repository.get_slot(session, booking_data.slot_id)
    if slot is None:
        raise BookingError("Procurement slot not found", 404)
    if slot.centre_id != centre.id:
        raise BookingError("Procurement slot does not belong to the selected centre", 422)
    if procurement_repository.is_slot_expired(slot):
        raise BookingError("Procurement slot has expired", 409)

    try:
        if not procurement_repository.reserve_slot_capacity(session, slot.id):
            raise BookingError("Procurement slot is full", 409)

        booking = booking_repository.create_booking(
            session,
            Booking(
                farmer_id=farmer.id,
                centre_id=centre.id,
                slot_id=slot.id,
                crop_type=booking_data.crop_type,
                quantity_kg=booking_data.quantity_kg,
                status=BookingStatus.BOOKED,
            ),
        )
        session.commit()
        session.refresh(booking)
        return booking
    except Exception:
        session.rollback()
        raise
