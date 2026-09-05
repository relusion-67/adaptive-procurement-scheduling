from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import ProcurementCentre, ProcurementSlot


def list_active_centres(session: Session) -> list[ProcurementCentre]:
    return list(
        session.scalars(
            select(ProcurementCentre)
            .where(ProcurementCentre.active.is_(True))
            .order_by(ProcurementCentre.id)
        )
    )


def get_centre(session: Session, centre_id: int) -> ProcurementCentre | None:
    return session.get(ProcurementCentre, centre_id)


def get_centre_for_update(session: Session, centre_id: int) -> ProcurementCentre | None:
    return session.scalar(
        select(ProcurementCentre)
        .where(ProcurementCentre.id == centre_id)
        .with_for_update()
    )


def _slot_end_datetime(slot: ProcurementSlot) -> datetime:
    """Combine a slot's date and end time into a comparable instant.

    Mirrors the scheduling engine's treatment of slot date/time values as
    naive wall-clock values interpreted as UTC, so the two stay consistent.
    """
    return datetime.combine(slot.slot_date, slot.end_time, tzinfo=timezone.utc)


def is_slot_expired(
    slot: ProcurementSlot, *, now: datetime | None = None
) -> bool:
    """Return whether a procurement slot's booking window has ended."""
    if now is None:
        now = datetime.now(timezone.utc)
    return _slot_end_datetime(slot) < now


def list_usable_slots(
    session: Session, centre_id: int, *, now: datetime | None = None
) -> list[ProcurementSlot]:
    """Slots at ``centre_id`` with remaining capacity that have not ended.

    A slot remains usable while any part of its window is still ahead of
    ``now`` (defaults to the current time), so a slot later today stays
    visible while a slot whose window has already elapsed is excluded.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    candidates = session.scalars(
        select(ProcurementSlot)
        .where(
            ProcurementSlot.centre_id == centre_id,
            ProcurementSlot.capacity > 0,
        )
        .order_by(ProcurementSlot.slot_date, ProcurementSlot.start_time)
    )
    return [slot for slot in candidates if not is_slot_expired(slot, now=now)]


def get_slot(session: Session, slot_id: int) -> ProcurementSlot | None:
    return session.get(ProcurementSlot, slot_id)


def reserve_slot_capacity(session: Session, slot_id: int) -> bool:
    """Atomically reserve one remaining booking position in a slot."""
    result = session.execute(
        update(ProcurementSlot)
        .where(
            ProcurementSlot.id == slot_id,
            ProcurementSlot.capacity > 0,
        )
        .values(capacity=ProcurementSlot.capacity - 1)
    )
    return result.rowcount == 1
