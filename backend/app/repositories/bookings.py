from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, ProcurementSlot

# Bookings in these states still represent pending demand on a centre: they
# either haven't been served yet or are actively being served. Terminal
# states (COMPLETED, CANCELLED, MISSED) no longer occupy a place in line.
PENDING_BOOKING_STATUSES = (
    BookingStatus.BOOKED,
    BookingStatus.CHECKED_IN,
    BookingStatus.IN_QUEUE,
    BookingStatus.PROCESSING,
)


def create_booking(session: Session, booking: Booking) -> Booking:
    session.add(booking)
    session.flush()
    return booking


def get_booking(session: Session, booking_id: int) -> Booking | None:
    return session.get(Booking, booking_id)


def get_booking_for_update(session: Session, booking_id: int) -> Booking | None:
    return session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update()
    )


def list_pending_bookings_for_centre(session: Session, centre_id: int) -> list[Booking]:
    """Return a centre's not-yet-terminal bookings, ordered by their slot's
    date and start time.

    This is the "pending demand" view the adaptive scheduling engine uses to
    observe both farmers who have already checked in and farmers whose slot
    simply hasn't arrived yet, without requiring a QueueEntry to exist.
    """
    return list(
        session.scalars(
            select(Booking)
            .join(ProcurementSlot, Booking.slot_id == ProcurementSlot.id)
            .where(
                Booking.centre_id == centre_id,
                Booking.status.in_(PENDING_BOOKING_STATUSES),
            )
            .order_by(ProcurementSlot.slot_date, ProcurementSlot.start_time, Booking.id)
        )
    )
