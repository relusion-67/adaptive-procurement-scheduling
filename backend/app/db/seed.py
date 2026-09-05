from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    Booking,
    BookingStatus,
    Farmer,
    NotificationChannel,
    NotificationLog,
    ProcurementCentre,
    ProcurementSlot,
    QueueEntry,
    QueueStatus,
    ThroughputSnapshot,
)


DEMO_CENTRES = (
    {
        "name": "Thanjavur Central Procurement Centre",
        "code": "TNJ-CENTRAL-01",
        "district": "Thanjavur",
        "daily_capacity": 180,
    },
    {
        "name": "Kumbakonam Procurement Centre",
        "code": "KUM-01",
        "district": "Thanjavur",
        "daily_capacity": 150,
    },
)

DEMO_FARMERS = (
    {"name": "Arun Kumar", "phone": "9000000001", "village": "Vallam"},
    {"name": "Meena Devi", "phone": "9000000002", "village": "Papanasam"},
    {"name": "R. Selvam", "phone": "9000000003", "village": "Orathanadu"},
    {"name": "Lakshmi Priya", "phone": "9000000004", "village": "Swamimalai"},
    {"name": "Muthuvel", "phone": "9000000005", "village": "Thiruvaiyaru"},
)

# The demo dataset used to pin bookings to fixed October 2026 dates. That
# meant the seeded slots quietly became unbookable "past" data once that
# week elapsed. Demo dates are now generated relative to whenever the seed
# actually runs (see `_demo_dates`), so a fresh seed always produces
# usable near-future slots regardless of the current date.
#
# Offsets deliberately start at +1 (tomorrow) rather than +0 (today):
# app/services/queue.py's early-check-in guard only restricts check-ins for
# a slot dated exactly "today" (see `_reject_early_check_in`), specifically
# because it was designed around demo data that never lands on the current
# date. Keeping demo dates strictly in the future preserves that existing,
# already-validated behavior instead of requiring changes to the check-in
# guard.
DEMO_DAY_OFFSETS = (10, 11, 12)  # +10, +11, +12 days
# Positional indices (0, 1, 2) into the tuple returned by `_demo_dates()`,
# used by DEMO_BOOKINGS below to reference "the seed's 1st/2nd/3rd demo
# date" without hardcoding an actual calendar date or day-count offset.
DEMO_DATE_POSITIONS = (0, 1, 2)
DEMO_TIME_WINDOWS = (
    (time(9, 0), time(10, 0)),
    (time(10, 30), time(11, 30)),
    (time(14, 0), time(15, 0)),
)

DEMO_BOOKINGS = (
    {
        "phone": "9000000001",
        "centre_code": "TNJ-CENTRAL-01",
        "date_offset": DEMO_DATE_POSITIONS[0],
        "start_time": time(9, 0),
        "crop_type": "Paddy",
        "quantity_kg": Decimal("1250.00"),
        "status": BookingStatus.CHECKED_IN,
    },
    {
        "phone": "9000000002",
        "centre_code": "TNJ-CENTRAL-01",
        "date_offset": DEMO_DATE_POSITIONS[0],
        "start_time": time(10, 30),
        "crop_type": "Groundnut",
        "quantity_kg": Decimal("680.00"),
        "status": BookingStatus.IN_QUEUE,
    },
    {
        "phone": "9000000003",
        "centre_code": "KUM-01",
        "date_offset": DEMO_DATE_POSITIONS[1],
        "start_time": time(9, 0),
        "crop_type": "Black Gram",
        "quantity_kg": Decimal("420.00"),
        "status": BookingStatus.BOOKED,
    },
    {
        "phone": "9000000004",
        "centre_code": "KUM-01",
        "date_offset": DEMO_DATE_POSITIONS[1],
        "start_time": time(10, 30),
        "crop_type": "Cotton",
        "quantity_kg": Decimal("940.00"),
        "status": BookingStatus.PROCESSING,
    },
    {
        "phone": "9000000005",
        "centre_code": "TNJ-CENTRAL-01",
        "date_offset": DEMO_DATE_POSITIONS[2],
        "start_time": time(14, 0),
        "crop_type": "Paddy",
        "quantity_kg": Decimal("1100.00"),
        "status": BookingStatus.BOOKED,
    },
)


def _demo_dates(today: date | None = None) -> tuple[date, ...]:
    """Return the rolling demo dates, anchored to ``today`` (or the real
    current date when not provided).

    Kept deliberately simple: a small rolling window of near-future dates
    so the seeded data is always usable on whatever day the seed is run,
    without adding an external dependency or a new table.
    """
    base = today if today is not None else date.today()
    return tuple(base + timedelta(days=offset) for offset in DEMO_DAY_OFFSETS)


def _record_counts(session: Session) -> dict[str, int]:
    models = {
        "centres": ProcurementCentre,
        "farmers": Farmer,
        "slots": ProcurementSlot,
        "bookings": Booking,
        "queue_entries": QueueEntry,
        "throughput_snapshots": ThroughputSnapshot,
        "notification_logs": NotificationLog,
    }
    return {
        name: session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in models.items()
    }


def seed_demo_data(session: Session, today: date | None = None) -> dict[str, int]:
    """Create the demo dataset and return the resulting table counts.

    Slot/booking dates are generated relative to ``today`` (or the real
    current date when not provided) so the seeded data stays usable no
    matter when the seed is actually run.
    """
    demo_dates = _demo_dates(today)
    try:
        centres: dict[str, ProcurementCentre] = {}
        for centre_data in DEMO_CENTRES:
            centre = session.scalar(
                select(ProcurementCentre).where(
                    ProcurementCentre.code == centre_data["code"]
                )
            )
            if centre is None:
                centre = ProcurementCentre(**centre_data)
                session.add(centre)
            centres[centre_data["code"]] = centre
        session.flush()

        farmers: dict[str, Farmer] = {}
        for farmer_data in DEMO_FARMERS:
            farmer = session.scalar(
                select(Farmer).where(Farmer.phone == farmer_data["phone"])
            )
            if farmer is None:
                farmer = Farmer(**farmer_data)
                session.add(farmer)
            farmers[farmer_data["phone"]] = farmer
        session.flush()

        slots: dict[tuple[str, date, time], ProcurementSlot] = {}
        for centre_code, centre in centres.items():
            for slot_date in demo_dates:
                for start_time, end_time in DEMO_TIME_WINDOWS:
                    slot = session.scalar(
                        select(ProcurementSlot).where(
                            ProcurementSlot.centre_id == centre.id,
                            ProcurementSlot.slot_date == slot_date,
                            ProcurementSlot.start_time == start_time,
                        )
                    )
                    if slot is None:
                        slot = ProcurementSlot(
                            centre_id=centre.id,
                            slot_date=slot_date,
                            start_time=start_time,
                            end_time=end_time,
                            capacity=20,
                        )
                        session.add(slot)
                    slots[(centre_code, slot_date, start_time)] = slot
        session.flush()

        bookings: dict[str, Booking] = {}
        for booking_data in DEMO_BOOKINGS:
            farmer = farmers[booking_data["phone"]]
            centre = centres[booking_data["centre_code"]]
            slot = slots[
                (
                    booking_data["centre_code"],
                    demo_dates[booking_data["date_offset"]],
                    booking_data["start_time"],
                )
            ]
            booking = session.scalar(
                select(Booking).where(
                    Booking.farmer_id == farmer.id,
                    Booking.slot_id == slot.id,
                )
            )
            if booking is None:
                booking = Booking(
                    farmer_id=farmer.id,
                    centre_id=centre.id,
                    slot_id=slot.id,
                    crop_type=booking_data["crop_type"],
                    quantity_kg=booking_data["quantity_kg"],
                    status=booking_data["status"],
                )
                session.add(booking)
            bookings[booking_data["phone"]] = booking
        session.flush()

        queue_data = (
            ("9000000001", "TNJ-CENTRAL-01", 101, QueueStatus.WAITING),
            ("9000000002", "TNJ-CENTRAL-01", 102, QueueStatus.CALLED),
            ("9000000004", "KUM-01", 201, QueueStatus.SERVING),
        )
        for phone, centre_code, token_number, queue_status in queue_data:
            booking = bookings[phone]
            queue_entry = session.scalar(
                select(QueueEntry).where(QueueEntry.booking_id == booking.id)
            )
            if queue_entry is None:
                session.add(
                    QueueEntry(
                        centre_id=centres[centre_code].id,
                        booking_id=booking.id,
                        token_number=token_number,
                        queue_status=queue_status,
                    )
                )
        session.flush()

        snapshot_data = (
            ("TNJ-CENTRAL-01", Decimal("12.50")),
            ("KUM-01", Decimal("14.00")),
        )
        snapshot_at = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
        for centre_code, minutes_per_farmer in snapshot_data:
            snapshot = session.scalar(
                select(ThroughputSnapshot).where(
                    ThroughputSnapshot.centre_id == centres[centre_code].id,
                    ThroughputSnapshot.snapshot_at == snapshot_at,
                )
            )
            if snapshot is None:
                session.add(
                    ThroughputSnapshot(
                        centre_id=centres[centre_code].id,
                        snapshot_at=snapshot_at,
                        avg_minutes_per_farmer=minutes_per_farmer,
                    )
                )

        notification_data: tuple[tuple[str, NotificationChannel, str, dict[str, Any]], ...] = (
            (
                "9000000001",
                NotificationChannel.SMS,
                "check_in_confirmation",
                {"token_number": 101, "centre_code": "TNJ-CENTRAL-01"},
            ),
            (
                "9000000002",
                NotificationChannel.IVR,
                "queue_call",
                {"token_number": 102, "centre_code": "TNJ-CENTRAL-01"},
            ),
        )
        for phone, channel, template_key, payload_json in notification_data:
            booking = bookings[phone]
            notification = session.scalar(
                select(NotificationLog).where(
                    NotificationLog.booking_id == booking.id,
                    NotificationLog.channel == channel,
                    NotificationLog.template_key == template_key,
                )
            )
            if notification is None:
                session.add(
                    NotificationLog(
                        booking_id=booking.id,
                        channel=channel,
                        template_key=template_key,
                        payload_json=payload_json,
                        sent_at=datetime(2026, 10, 1, 8, 45, tzinfo=timezone.utc),
                        delivery_state="DELIVERED",
                    )
                )

        session.commit()
    except Exception:
        session.rollback()
        raise

    return _record_counts(session)


def main() -> None:
    with SessionLocal() as session:
        counts = seed_demo_data(session)
    count_text = ", ".join(f"{name}={count}" for name, count in counts.items())
    print(f"Demo data seeded: {count_text}")


if __name__ == "__main__":
    main()
