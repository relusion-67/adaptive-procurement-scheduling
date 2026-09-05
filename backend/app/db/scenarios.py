"""Dev-only demo/stress-test fixture for the adaptive scheduling engine.

THIS FILE IS NOT IMPORTED BY THE APPLICATION. It is a standalone CLI script,
in the same spirit as ``app/db/seed.py``, that manipulates a small, isolated
set of demo rows (a dedicated demo centre, farmer, slot and booking) so the
Phase 3 adaptive engine in ``app/services/scheduling.py`` can be driven
reliably through ON_TRACK -> AT_RISK -> DELAYED for a live demo, without
touching that engine's code, any existing API route, or any of the regular
seeded/production data.

How it works
------------
``scheduling.py`` classifies a not-yet-checked-in booking using a purely
data-driven forecast (see ``_forecast_estimate``):

    current_queue_work_minutes  = live_queue_count * avg_minutes_per_farmer
    minutes_until_slot_start    = max(0, slot_start - now)
    projected_carryover_minutes = max(0, current_queue_work_minutes
                                         - minutes_until_slot_start)
    overrun_minutes             = projected_carryover_minutes - slot_duration

    overrun <= 10  -> ON_TRACK
    overrun <= 45  -> AT_RISK
    overrun >  45  -> DELAYED

This script keeps the demo booking's slot anchored a fixed, short window
into the future (it never becomes a "past" slot) and instead drives the
state purely by changing how backed up the centre's *live queue* is and how
slow its *throughput* is -- i.e. exactly the "queue/service slowdown"
scenario asked for. That mirrors how ``tests/test_scheduling.py`` already
builds each state, just packaged as a reusable fixture instead of one-off
test data.

Usage (run from the backend/ directory, against your local Postgres):

    python -m app.db.scenarios normal              # -> ON_TRACK / KEEP_SLOT
    python -m app.db.scenarios at_risk              # -> AT_RISK / WARN_FARMER
    python -m app.db.scenarios delayed              # -> DELAYED / PROPOSE_NEW_SLOT
    python -m app.db.scenarios delayed_alt_centre   # -> DELAYED / RECOMMEND_ALTERNATE_CENTRE
    python -m app.db.scenarios status                # read-only: show current state
    python -m app.db.scenarios reset                 # back to the normal baseline

Each command prints the demo booking id and centre id plus the exact GET
request to poll against your running dev server, e.g.:

    GET /api/scheduling/bookings/<booking_id>

Safety
------
- Refuses to run when ``settings.app_env == "production"``.
- Only ever touches rows it owns (matched by the fixed demo centre codes /
  farmer phone numbers below) -- it never reads or writes the regular
  ``seed.py`` demo data or any other row.
- No new API endpoint, no scheduling-engine change, no frontend change.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    Booking,
    BookingStatus,
    Farmer,
    ProcurementCentre,
    ProcurementSlot,
    QueueEntry,
    QueueStatus,
    ThroughputSnapshot,
)
from app.repositories import throughput as throughput_repository

# --------------------------------------------------------------------------
# Fixed identifiers for the isolated demo dataset this script owns.
# Distinct from seed.py's TNJ-CENTRAL-01 / KUM-01 / 90000000xx data so the
# two fixtures can never collide or interfere with each other.
# --------------------------------------------------------------------------

DEMO_CENTRE = {
    "name": "SIH Demo Procurement Centre",
    "code": "SIH-DEMO-01",
    "district": "Demo District",
    "daily_capacity": 999,
}
ALT_CENTRE = {
    "name": "SIH Demo Alternate Centre",
    "code": "SIH-DEMO-02",
    "district": "Demo District",
    "daily_capacity": 999,
}
DEMO_FARMER = {"name": "SIH Demo Farmer", "phone": "9999999999", "village": "Demo Village"}
FILLER_FARMER = {
    "name": "SIH Demo Filler Farmer",
    "phone": "9999999998",
    "village": "Demo Village",
}

# The demo booking's own slot always starts this many minutes from "now"
# (never in the past) and runs for this long. Only queue depth / throughput
# change between stages -- the slot itself always looks like a normal,
# perfectly reasonable upcoming booking.
MINUTES_UNTIL_SLOT_START = 10
SLOT_DURATION_MINUTES = 60

# Token numbers reserved for the filler queue pool, kept well clear of any
# tokens a real/seeded booking would use at this centre.
FILLER_TOKEN_BASE = 9000
FILLER_POOL_SIZE = 10

# Later-slot offsets (minutes from "now") used only for the DELAYED
# recommendation paths, so PROPOSE_NEW_SLOT / RECOMMEND_ALTERNATE_CENTRE
# have something concrete to point at.
LATER_SAME_CENTRE_OFFSET = 180
ALT_CENTRE_SLOT_OFFSET = 200


@dataclass
class StageResult:
    stage: str
    booking_id: int
    centre_id: int
    slot_id: int
    live_queue_count: int
    avg_minutes_per_farmer: Decimal
    expected_status: str
    expected_recommendation: str
    notes: str


# --------------------------------------------------------------------------
# Get-or-create helpers (mirrors the idiom already used in app/db/seed.py)
# --------------------------------------------------------------------------


def _get_or_create_centre(session: Session, data: dict) -> ProcurementCentre:
    centre = session.scalar(
        select(ProcurementCentre).where(ProcurementCentre.code == data["code"])
    )
    if centre is None:
        centre = ProcurementCentre(**data)
        session.add(centre)
        session.flush()
    elif not centre.active:
        centre.active = True
        session.flush()
    return centre


def _get_or_create_farmer(session: Session, data: dict) -> Farmer:
    farmer = session.scalar(select(Farmer).where(Farmer.phone == data["phone"]))
    if farmer is None:
        farmer = Farmer(**data)
        session.add(farmer)
        session.flush()
    return farmer


def _split_date_time(dt: datetime) -> tuple:
    return dt.date(), dt.time()


def _future_window(
    minutes_until_start: int, duration_minutes: int
) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes, both guaranteed to fall on the same
    calendar day (the domain model stores slot_date + start_time/end_time
    separately, so a midnight rollover would corrupt the slot). If the
    naive offset would cross midnight, anchor to 09:00 UTC the next day
    instead -- still deterministic, just avoids the edge case."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(minutes=minutes_until_start)
    end = start + timedelta(minutes=duration_minutes)
    if start.date() != end.date():
        start = (now + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(minutes=duration_minutes)
    return start, end


def _get_or_create_demo_slot(
    session: Session, centre: ProcurementCentre, capacity: int = 999
) -> ProcurementSlot:
    """The one slot the demo booking always uses. Reused (not recreated)
    across stage runs -- only its date/time are repositioned relative to
    "now" each time a stage runs, so the demo booking id stays stable."""
    slot = session.scalar(
        select(ProcurementSlot)
        .join(Booking, Booking.slot_id == ProcurementSlot.id)
        .join(Farmer, Booking.farmer_id == Farmer.id)
        .where(
            ProcurementSlot.centre_id == centre.id,
            Farmer.phone == DEMO_FARMER["phone"],
        )
        .limit(1)
    )
    start, end = _future_window(MINUTES_UNTIL_SLOT_START, SLOT_DURATION_MINUTES)
    slot_date, start_time = _split_date_time(start)
    _, end_time = _split_date_time(end)
    if slot is None:
        slot = ProcurementSlot(
            centre_id=centre.id,
            slot_date=slot_date,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
        )
        session.add(slot)
        session.flush()
    else:
        slot.slot_date = slot_date
        slot.start_time = start_time
        slot.end_time = end_time
        slot.capacity = capacity
        session.flush()
    return slot


def _get_or_create_demo_booking(
    session: Session,
    farmer: Farmer,
    centre: ProcurementCentre,
    slot: ProcurementSlot,
) -> Booking:
    booking = session.scalar(
        select(Booking).where(
            Booking.farmer_id == farmer.id,
            Booking.centre_id == centre.id,
        )
    )
    if booking is None:
        booking = Booking(
            farmer_id=farmer.id,
            centre_id=centre.id,
            slot_id=slot.id,
            crop_type="SIH Demo Crop",
            quantity_kg=Decimal("500.00"),
            status=BookingStatus.BOOKED,
        )
        session.add(booking)
        session.flush()
    else:
        # Always keep it in the not-yet-checked-in / forecast path and
        # pointed at the (repositioned) demo slot.
        booking.status = BookingStatus.BOOKED
        booking.slot_id = slot.id
        session.flush()
    return booking


def _ensure_filler_pool(
    session: Session,
    centre: ProcurementCentre,
    slot: ProcurementSlot,
    farmer: Farmer,
) -> list[QueueEntry]:
    """A fixed-size, idempotent pool of "other farmers" queue entries used
    to represent live queue depth at the demo centre. Reused across runs
    (statuses get flipped, not recreated) so repeated demo runs don't pile
    up rows without bound."""
    entries: list[QueueEntry] = []
    for i in range(FILLER_POOL_SIZE):
        token_number = FILLER_TOKEN_BASE + i
        entry = session.scalar(
            select(QueueEntry).where(
                QueueEntry.centre_id == centre.id,
                QueueEntry.token_number == token_number,
            )
        )
        if entry is None:
            booking = Booking(
                farmer_id=farmer.id,
                centre_id=centre.id,
                slot_id=slot.id,
                crop_type="SIH Demo Filler Crop",
                quantity_kg=Decimal("100.00"),
                status=BookingStatus.IN_QUEUE,
            )
            session.add(booking)
            session.flush()
            entry = QueueEntry(
                centre_id=centre.id,
                booking_id=booking.id,
                token_number=token_number,
                queue_status=QueueStatus.DONE,
                served_at=datetime.now(timezone.utc),
            )
            session.add(entry)
            session.flush()
        entries.append(entry)
    return entries


def _set_live_queue_count(session: Session, pool: list[QueueEntry], count: int) -> None:
    """Flip exactly ``count`` filler queue entries to WAITING (live) and the
    rest to DONE (not live), deterministically."""
    now = datetime.now(timezone.utc)
    for index, entry in enumerate(pool):
        if index < count:
            entry.queue_status = QueueStatus.WAITING
            entry.checked_in_at = now
            entry.called_at = None
            entry.served_at = None
        else:
            entry.queue_status = QueueStatus.DONE
            entry.served_at = now
    session.flush()


def _add_throughput_snapshot(
    session: Session, centre_id: int, avg_minutes_per_farmer: Decimal
) -> None:
    throughput_repository.create_snapshot(session, centre_id, avg_minutes_per_farmer)


def _get_or_create_later_slot(
    session: Session,
    centre: ProcurementCentre,
    offset_minutes: int,
    capacity: int,
) -> ProcurementSlot:
    """A second, later slot at ``centre`` used only so the DELAYED
    recommendation paths (PROPOSE_NEW_SLOT / RECOMMEND_ALTERNATE_CENTRE)
    have something concrete to find. Identified by a fixed marker
    (capacity is intentionally NOT part of the lookup key, since stages
    toggle it between 0 and non-zero)."""
    start, end = _future_window(offset_minutes, SLOT_DURATION_MINUTES)
    slot_date, start_time = _split_date_time(start)
    _, end_time = _split_date_time(end)

    # Reuse-by-role: this fixture only ever needs one "later slot" per demo
    # centre, so it's identified simply as "the extra slot at this centre
    # that starts at this stage's fixed offset time-of-day" and repositioned
    # in place on every run, the same way _get_or_create_demo_slot works.
    later = session.scalar(
        select(ProcurementSlot).where(
            ProcurementSlot.centre_id == centre.id,
            ProcurementSlot.start_time == start_time,
        )
    )
    if later is None:
        later = ProcurementSlot(
            centre_id=centre.id,
            slot_date=slot_date,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
        )
        session.add(later)
        session.flush()
    else:
        later.slot_date = slot_date
        later.start_time = start_time
        later.end_time = end_time
        later.capacity = capacity
        session.flush()
    return later


# --------------------------------------------------------------------------
# Stages
# --------------------------------------------------------------------------


def _setup(session: Session) -> tuple[ProcurementCentre, Farmer, Farmer, ProcurementSlot, Booking]:
    centre = _get_or_create_centre(session, DEMO_CENTRE)
    farmer = _get_or_create_farmer(session, DEMO_FARMER)
    filler_farmer = _get_or_create_farmer(session, FILLER_FARMER)
    slot = _get_or_create_demo_slot(session, centre)
    booking = _get_or_create_demo_booking(session, farmer, centre, slot)
    return centre, farmer, filler_farmer, slot, booking


def stage_normal(session: Session) -> StageResult:
    """Normal centre conditions: empty live queue, fast service pace."""
    centre, _farmer, filler_farmer, slot, booking = _setup(session)
    pool = _ensure_filler_pool(session, centre, slot, filler_farmer)
    _set_live_queue_count(session, pool, count=0)
    avg = Decimal("8.00")
    _add_throughput_snapshot(session, centre.id, avg)
    session.commit()
    return StageResult(
        stage="normal",
        booking_id=booking.id,
        centre_id=centre.id,
        slot_id=slot.id,
        live_queue_count=0,
        avg_minutes_per_farmer=avg,
        expected_status="ON_TRACK",
        expected_recommendation="KEEP_SLOT",
        notes="Empty live queue, 8 min/farmer service pace: comfortably on track.",
    )


def stage_at_risk(session: Session) -> StageResult:
    """Queue/service slowdown: a handful of live farmers plus a slower
    average service pace pushes the projected overrun into (10, 45] min."""
    centre, _farmer, filler_farmer, slot, booking = _setup(session)
    pool = _ensure_filler_pool(session, centre, slot, filler_farmer)
    live_count = 6
    _set_live_queue_count(session, pool, count=live_count)
    avg = Decimal("16.00")
    _add_throughput_snapshot(session, centre.id, avg)
    session.commit()
    return StageResult(
        stage="at_risk",
        booking_id=booking.id,
        centre_id=centre.id,
        slot_id=slot.id,
        live_queue_count=live_count,
        avg_minutes_per_farmer=avg,
        expected_status="AT_RISK",
        expected_recommendation="WARN_FARMER",
        notes=(
            f"{live_count} farmers now live in queue at {avg} min/farmer: the "
            "queue won't fully drain before this slot starts, projecting a "
            "~26 min overrun (comfortable margin inside the 10-45 min band)."
        ),
    )


def stage_delayed(session: Session, alternate_centre: bool = False) -> StageResult:
    """Further degradation: queue depth and service pace both worsen,
    pushing the projected overrun well past 45 min."""
    centre, _farmer, filler_farmer, slot, booking = _setup(session)
    pool = _ensure_filler_pool(session, centre, slot, filler_farmer)
    live_count = 8
    _set_live_queue_count(session, pool, count=live_count)
    avg = Decimal("25.00")
    _add_throughput_snapshot(session, centre.id, avg)

    # Always keep a later same-centre slot present; whether it's usable
    # (capacity > 0) decides PROPOSE_NEW_SLOT vs RECOMMEND_ALTERNATE_CENTRE.
    later_capacity = 0 if alternate_centre else 20
    _get_or_create_later_slot(session, centre, LATER_SAME_CENTRE_OFFSET, later_capacity)

    stage_name = "delayed"
    expected_recommendation = "PROPOSE_NEW_SLOT"
    notes = (
        f"{live_count} farmers live in queue at {avg} min/farmer: projected "
        "overrun ~130 min, well past the 45 min DELAYED threshold. A later "
        "slot with spare capacity exists at this centre."
    )
    if alternate_centre:
        alt_centre = _get_or_create_centre(session, ALT_CENTRE)
        _get_or_create_later_slot(session, alt_centre, ALT_CENTRE_SLOT_OFFSET, 20)
        stage_name = "delayed_alt_centre"
        expected_recommendation = "RECOMMEND_ALTERNATE_CENTRE"
        notes = (
            f"{live_count} farmers live in queue at {avg} min/farmer: projected "
            "overrun ~130 min. The same-centre later slot has been filled "
            f"(capacity 0), so the engine should fall back to centre "
            f"'{ALT_CENTRE['code']}', which has a usable future slot."
        )

    session.commit()
    return StageResult(
        stage=stage_name,
        booking_id=booking.id,
        centre_id=centre.id,
        slot_id=slot.id,
        live_queue_count=live_count,
        avg_minutes_per_farmer=avg,
        expected_status="DELAYED",
        expected_recommendation=expected_recommendation,
        notes=notes,
    )


def stage_status(session: Session) -> StageResult | None:
    """Read-only: report the demo booking's current inputs without
    mutating anything. Returns None if the demo fixture hasn't been run
    yet."""
    centre = session.scalar(
        select(ProcurementCentre).where(ProcurementCentre.code == DEMO_CENTRE["code"])
    )
    farmer = session.scalar(select(Farmer).where(Farmer.phone == DEMO_FARMER["phone"]))
    if centre is None or farmer is None:
        return None
    booking = session.scalar(
        select(Booking).where(Booking.farmer_id == farmer.id, Booking.centre_id == centre.id)
    )
    if booking is None:
        return None
    snapshot = throughput_repository.get_latest_snapshot(session, centre.id)
    live_count = len(
        [
            e
            for e in session.scalars(
                select(QueueEntry).where(QueueEntry.centre_id == centre.id)
            ).all()
            if e.queue_status in (QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.SERVING)
        ]
    )
    return StageResult(
        stage="status",
        booking_id=booking.id,
        centre_id=centre.id,
        slot_id=booking.slot_id,
        live_queue_count=live_count,
        avg_minutes_per_farmer=(
            Decimal(snapshot.avg_minutes_per_farmer) if snapshot else Decimal("15.00")
        ),
        expected_status="(unknown - poll the API to see the live classification)",
        expected_recommendation="",
        notes="Read-only snapshot of current fixture inputs; nothing was changed.",
    )


STAGES = {
    "normal": stage_normal,
    "at_risk": stage_at_risk,
    "delayed": stage_delayed,
    "delayed_alt_centre": lambda session: stage_delayed(session, alternate_centre=True),
    "reset": stage_normal,
}


def _print_result(result: StageResult) -> None:
    print(f"\n[scenario: {result.stage}]")
    print(f"  booking_id              = {result.booking_id}")
    print(f"  centre_id               = {result.centre_id}")
    print(f"  slot_id                 = {result.slot_id}")
    print(f"  live_queue_count        = {result.live_queue_count}")
    print(f"  avg_minutes_per_farmer  = {result.avg_minutes_per_farmer}")
    print(f"  expected_status         = {result.expected_status}")
    print(f"  expected_recommendation = {result.expected_recommendation}")
    print(f"  notes                   = {result.notes}")
    print(f"\n  Verify with:  GET {settings.api_prefix}/scheduling/bookings/{result.booking_id}")
    print(f"  Or centre view: GET {settings.api_prefix}/scheduling/centres/{result.centre_id}\n")


def main() -> None:
    if settings.app_env.lower() == "production":
        print(
            "Refusing to run: app_env is 'production'. This script is for "
            "local/dev demo use only.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    parser = argparse.ArgumentParser(
        description="Deterministically drive the demo booking through the "
        "adaptive scheduling engine's states."
    )
    parser.add_argument(
        "stage",
        choices=[*STAGES.keys(), "status"],
        help="Which scenario stage to apply.",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.stage == "status":
            result = stage_status(session)
            if result is None:
                print(
                    "Demo fixture hasn't been created yet. Run "
                    "'python -m app.db.scenarios normal' first."
                )
                return
        else:
            result = STAGES[args.stage](session)

    _print_result(result)


if __name__ == "__main__":
    main()
