from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed import seed_demo_data
from app.db.session import get_db
from app.main import app
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
from app.services.eta import DEFAULT_AVERAGE_SERVICE_MINUTES
from tests._auth_helpers import auth_headers, create_admin

# --------------------------------------------------------------------------
# Fixtures (mirrors the sqlite + Alembic pattern used across the test suite)
# --------------------------------------------------------------------------


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'scheduling.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session)
    # Start from a clean queue/booking/throughput state so each test builds
    # its own deterministic scenario instead of depending on the fixed demo
    # queue entries or the seeded snapshot's exact value.
    session.execute(delete(QueueEntry))
    session.execute(delete(ThroughputSnapshot))
    session.execute(update(Booking).values(status=BookingStatus.BOOKED))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        command.downgrade(alembic_cfg, "base")


@pytest.fixture
async def client(db_session: Session) -> AsyncClient:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Regression/business-logic tests in this file exercise the existing
    # workflows end-to-end and aren't themselves testing authorization, so
    # the default client authenticates as an ADMIN (who can reach every
    # endpoint). Dedicated authorization/IDOR behavior is covered by
    # tests/test_security.py using its own, more narrowly-scoped clients.
    admin = create_admin(db_session, email="test_scheduling-admin@example.test")
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=auth_headers(admin),
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def centre(session: Session, code: str = "TNJ-CENTRAL-01") -> ProcurementCentre:
    result = session.scalar(select(ProcurementCentre).where(ProcurementCentre.code == code))
    assert result is not None
    return result


def farmer(session: Session, phone: str = "9000000001") -> Farmer:
    result = session.scalar(select(Farmer).where(Farmer.phone == phone))
    assert result is not None
    return result


def booked_booking(session: Session, centre_id: int, offset: int = 0) -> Booking:
    bookings = list(
        session.scalars(
            select(Booking)
            .where(Booking.centre_id == centre_id, Booking.status == BookingStatus.BOOKED)
            .order_by(Booking.id)
        )
    )
    assert len(bookings) > offset
    return bookings[offset]


def add_snapshot(session: Session, centre_id: int, avg_minutes: str) -> None:
    session.add(
        ThroughputSnapshot(
            centre_id=centre_id,
            snapshot_at=datetime.now(timezone.utc),
            avg_minutes_per_farmer=Decimal(avg_minutes),
        )
    )
    session.commit()


def make_slot(
    session: Session,
    centre_id: int,
    *,
    end_offset: timedelta,
    duration: timedelta = timedelta(hours=1),
    capacity: int = 5,
) -> ProcurementSlot:
    """Create a slot whose end time sits ``end_offset`` away from now, so
    tests can deterministically push a booking into ON_TRACK/AT_RISK/DELAYED
    without depending on the demo data's fixed October 2026 dates."""
    end_dt = datetime.now(timezone.utc) + end_offset
    start_dt = end_dt - duration
    slot = ProcurementSlot(
        centre_id=centre_id,
        slot_date=end_dt.date(),
        start_time=start_dt.time(),
        end_time=end_dt.time(),
        capacity=capacity,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)
    return slot


def make_booking(
    session: Session,
    *,
    farmer_id: int,
    centre_id: int,
    slot_id: int,
    status: BookingStatus = BookingStatus.BOOKED,
) -> Booking:
    booking = Booking(
        farmer_id=farmer_id,
        centre_id=centre_id,
        slot_id=slot_id,
        crop_type="Paddy",
        quantity_kg=Decimal("100.00"),
        status=status,
    )
    session.add(booking)
    session.commit()
    session.refresh(booking)
    return booking


def deactivate_other_centres(session: Session, keep_ids: set[int]) -> None:
    """Deactivate every existing centre except the given ones, so alternate-
    centre search has a clean, controlled slate to search over."""
    all_centres = session.scalars(select(ProcurementCentre)).all()
    for c in all_centres:
        if c.id not in keep_ids:
            c.active = False
    session.commit()


def assert_close_minutes(actual: str, expected_minutes: float, tolerance: float = 1.0) -> None:
    """The forecast path anchors to real wall-clock `now()` at two points
    (slot creation in the test, and the request itself), so exact Decimal
    equality is flaky by design. Assert within a small tolerance instead."""
    assert abs(float(Decimal(actual)) - expected_minutes) < tolerance, (
        f"expected ~{expected_minutes} min, got {actual}"
    )


async def check_in(client: AsyncClient, booking: Booking) -> dict[str, object]:
    response = await client.post(
        "/api/queue/check-in",
        json={"booking_id": booking.id, "centre_id": booking.centre_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Not-found handling
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_booking_not_found_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/scheduling/bookings/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Booking not found"


@pytest.mark.anyio
async def test_centre_not_found_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/scheduling/centres/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Procurement centre not found"


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upcoming_booking_far_in_future_is_on_track(
    client: AsyncClient, db_session: Session
) -> None:
    """An upcoming booking (no QueueEntry yet) whose slot is comfortably in
    the future should forecast ON_TRACK / KEEP_SLOT."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")
    slot = make_slot(db_session, centre_record.id, end_offset=timedelta(days=2))
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "ON_TRACK"
    assert body["recommendation"] == "KEEP_SLOT"
    assert body["is_forecast"] is True
    assert Decimal(body["average_service_minutes"]) == Decimal("12.50")
    assert "no live queue entry yet" in body["explanation"]


@pytest.mark.anyio
async def test_booking_becomes_at_risk(client: AsyncClient, db_session: Session) -> None:
    """A slot that ended ~20 minutes ago, with nobody ahead, produces an
    overrun inside the (10, 45] minute AT_RISK band."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")
    slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=-20))
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "AT_RISK"
    assert body["recommendation"] == "WARN_FARMER"


@pytest.mark.anyio
async def test_booking_becomes_delayed(client: AsyncClient, db_session: Session) -> None:
    """A slot that ended well over 45 minutes ago is DELAYED."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")
    slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=-90))
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "DELAYED"


@pytest.mark.anyio
async def test_missed_booking_is_always_delayed(
    client: AsyncClient, db_session: Session
) -> None:
    """A booking already recorded as MISSED is DELAYED regardless of what
    the numeric estimate would otherwise say (slot is far in the future
    here, which would normally forecast ON_TRACK)."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")
    slot = make_slot(db_session, centre_record.id, end_offset=timedelta(days=3))
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=slot.id,
        status=BookingStatus.MISSED,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "DELAYED"
    assert "already MISSED" in body["explanation"]


# --------------------------------------------------------------------------
# OBSERVE / ESTIMATE: checked-in vs. forecast paths
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_checked_in_booking_uses_live_queue_position(
    client: AsyncClient, db_session: Session
) -> None:
    """A booking with a live QueueEntry should use the real queue position
    (reusing the ETA service), not the forecast path."""
    centre_record = centre(db_session)
    first_booking = booked_booking(db_session, centre_record.id)
    second_booking = booked_booking(db_session, centre_record.id, offset=1)
    await check_in(client, first_booking)
    second_entry = await check_in(client, second_booking)

    eta_response = await client.get(f"/api/queue/{second_entry['id']}/eta")
    assert eta_response.status_code == 200
    eta_body = eta_response.json()

    response = await client.get(f"/api/scheduling/bookings/{second_booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["is_forecast"] is False
    assert body["farmers_ahead"] == eta_body["farmers_ahead"] == 1
    assert Decimal(body["estimated_wait_minutes"]) == Decimal(eta_body["estimated_wait_minutes"])
    assert "live position in the queue" in body["explanation"]


@pytest.mark.anyio
async def test_upcoming_booking_with_scheduled_bookings_ahead(
    client: AsyncClient, db_session: Session
) -> None:
    """A booking that hasn't checked in should forecast farmers_ahead from
    still-BOOKED bookings scheduled earlier at the same centre (with no
    live queue in play here), and the wait is anchored to the slot start,
    not to `now`."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "10.00")

    earlier_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=1))
    later_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=3))

    farmer_a = farmer(db_session, "9000000001")
    farmer_b = farmer(db_session, "9000000002")

    earlier_booking = make_booking(
        db_session, farmer_id=farmer_a.id, centre_id=centre_record.id, slot_id=earlier_slot.id
    )
    target_booking = make_booking(
        db_session, farmer_id=farmer_b.id, centre_id=centre_record.id, slot_id=later_slot.id
    )

    response = await client.get(f"/api/scheduling/bookings/{target_booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["is_forecast"] is True
    # Only the earlier-scheduled booking counts as ahead; the demo seed's
    # other BOOKED bookings live on 2026-10 slots which sort after both of
    # these "now"-relative slots, so they don't count.
    assert body["farmers_ahead"] == 1
    # No live queue, so no carryover. Wait = minutes-until-slot-start (~120)
    # + the one pending booking ahead (10 min) = ~130 min, anchored to the
    # later_slot's own start time - NOT the old (and wrong) "10 min from
    # now" that a naive farmers_ahead x avg would have produced.
    assert_close_minutes(body["estimated_wait_minutes"], 130.0)
    assert body["booking_id"] == target_booking.id
    assert earlier_booking.id != target_booking.id  # sanity: distinct bookings


@pytest.mark.anyio
async def test_future_slot_where_queue_clears_before_slot_start(
    client: AsyncClient, db_session: Session
) -> None:
    """A live queue that will fully drain before this booking's future slot
    even starts must NOT be dumped onto the forecast wholesale. This is the
    core bug the corrected model fixes."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "10.00")

    # 2 farmers live in queue right now = 20 min of current work.
    queue_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=1))
    for phone in ("9000000001", "9000000002"):
        live_booking = make_booking(
            db_session,
            farmer_id=farmer(db_session, phone).id,
            centre_id=centre_record.id,
            slot_id=queue_slot.id,
        )
        await check_in(client, live_booking)

    # Target slot starts in ~2 hours - comfortably enough time (>20 min)
    # for the current queue to clear before the farmer's slot even begins.
    later_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=3))
    target_booking = make_booking(
        db_session,
        farmer_id=farmer(db_session, "9000000003").id,
        centre_id=centre_record.id,
        slot_id=later_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{target_booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["is_forecast"] is True
    # The 2-person live queue has fully drained (by the model's projection)
    # before this far-out slot starts, so it contributes 0 carryover -
    # NOT 2, which is what the old (incorrect) model would have reported.
    assert body["farmers_ahead"] == 0
    assert body["scheduling_status"] == "ON_TRACK"
    assert body["recommendation"] == "KEEP_SLOT"


@pytest.mark.anyio
async def test_future_slot_where_queue_cannot_clear_before_slot_start(
    client: AsyncClient, db_session: Session
) -> None:
    """A live queue that WON'T fully drain before this booking's slot
    starts should carry partial (not full, not zero) workload into the
    forecast."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "20.00")

    # 3 farmers live in queue right now = 60 min of current work.
    queue_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=1))
    for phone in ("9000000001", "9000000002", "9000000004"):
        live_booking = make_booking(
            db_session,
            farmer_id=farmer(db_session, phone).id,
            centre_id=centre_record.id,
            slot_id=queue_slot.id,
        )
        await check_in(client, live_booking)

    # Target slot starts in only ~30 minutes: 30 min of the 60 min queue
    # workload will still be outstanding when the slot begins.
    target_slot = make_slot(
        db_session, centre_record.id, end_offset=timedelta(minutes=45), duration=timedelta(minutes=15)
    )
    target_booking = make_booking(
        db_session,
        farmer_id=farmer(db_session, "9000000003").id,
        centre_id=centre_record.id,
        slot_id=target_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{target_booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["is_forecast"] is True
    # Carryover ~30 min at 20 min/farmer -> ~1.5 farmers-equivalent, i.e.
    # partial, neither the full 3 nor 0.
    assert 0 < body["farmers_ahead"] < 3
    assert_close_minutes(body["estimated_wait_minutes"], 60.0, tolerance=2.0)
    # Wait (~60 min) overruns the 15-min slot end by ~15 min -> AT_RISK.
    assert body["scheduling_status"] == "AT_RISK"
    assert body["recommendation"] == "WARN_FARMER"


@pytest.mark.anyio
async def test_forecast_does_not_double_count_a_booking_already_in_live_queue(
    client: AsyncClient, db_session: Session
) -> None:
    """A booking that has already checked in (and is thus in the live
    queue) must be represented exactly once in the forecast for a later
    booking - via queue carryover - never a second time as a 'pending
    booking scheduled ahead'."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "10.00")

    earlier_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=40))
    earlier_booking = make_booking(
        db_session,
        farmer_id=farmer(db_session, "9000000001").id,
        centre_id=centre_record.id,
        slot_id=earlier_slot.id,
    )
    await check_in(client, earlier_booking)  # now live in queue, 1 x 10 min = 10 min work

    # Target slot starts in ~5 minutes, so only 5 of the 10 min of queue
    # work will have cleared: 5 min carryover -> rounds to 1 farmer-
    # equivalent. If double counted, this would instead read 2.
    target_slot = make_slot(
        db_session, centre_record.id, end_offset=timedelta(minutes=35), duration=timedelta(minutes=30)
    )
    target_booking = make_booking(
        db_session,
        farmer_id=farmer(db_session, "9000000002").id,
        centre_id=centre_record.id,
        slot_id=target_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{target_booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["is_forecast"] is True
    assert body["farmers_ahead"] == 1
    assert "0 pending booking(s) scheduled ahead" in body["explanation"]


@pytest.mark.anyio
async def test_currently_active_slot_uses_full_queue_as_carryover(
    client: AsyncClient, db_session: Session
) -> None:
    """A slot that has already started (same-day / currently active) has
    zero 'time until slot start' left, so the full current queue workload
    is treated as carryover - but it's still weighed against the slot's
    remaining window, not blindly treated as delay."""
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "10.00")

    queue_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=1))
    live_booking = make_booking(
        db_session,
        farmer_id=farmer(db_session, "9000000001").id,
        centre_id=centre_record.id,
        slot_id=queue_slot.id,
    )
    await check_in(client, live_booking)  # 1 x 10 min = 10 min of current work

    # Target slot started 30 minutes ago and runs for another 30 minutes -
    # i.e. it is active right now.
    active_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=30), duration=timedelta(minutes=60))
    target_booking = make_booking(
        db_session,
        farmer_id=farmer(db_session, "9000000002").id,
        centre_id=centre_record.id,
        slot_id=active_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{target_booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["is_forecast"] is True
    # minutes_until_slot_start == 0 (already started) -> full 10 min of
    # queue work carries over as-is.
    assert body["farmers_ahead"] == 1
    assert_close_minutes(body["estimated_wait_minutes"], 10.0)
    # 10 min wait comfortably fits inside the slot's remaining 30-minute
    # window, so this is still ON_TRACK despite the live queue.
    assert body["scheduling_status"] == "ON_TRACK"
    assert body["recommendation"] == "KEEP_SLOT"


@pytest.mark.anyio
async def test_no_throughput_snapshot_falls_back_to_eta_default(
    client: AsyncClient, db_session: Session
) -> None:
    """With no ThroughputSnapshot at all, the scheduler must reuse the ETA
    service's existing 15-minute default rather than inventing a new one."""
    centre_record = centre(db_session)
    slot = make_slot(db_session, centre_record.id, end_offset=timedelta(hours=2))
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["average_service_minutes"]) == DEFAULT_AVERAGE_SERVICE_MINUTES


# --------------------------------------------------------------------------
# Recommendation / alternative search
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delayed_booking_with_same_centre_alternative_proposes_new_slot(
    client: AsyncClient, db_session: Session
) -> None:
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")
    past_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=-90))
    future_slot = make_slot(
        db_session, centre_record.id, end_offset=timedelta(days=1), capacity=5
    )
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=past_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "DELAYED"
    assert body["recommendation"] == "PROPOSE_NEW_SLOT"
    assert body["recommended_slot_id"] == future_slot.id
    assert body["recommended_centre_id"] == centre_record.id


@pytest.mark.anyio
async def test_delayed_booking_with_alternate_centre_option(
    client: AsyncClient, db_session: Session
) -> None:
    centre_a = centre(db_session, "TNJ-CENTRAL-01")
    centre_b = centre(db_session, "KUM-01")
    deactivate_other_centres(db_session, keep_ids={centre_a.id, centre_b.id})
    add_snapshot(db_session, centre_a.id, "12.50")

    # centre_a only has the one (past, DELAYED) slot - no later slot there.
    only_slot = make_slot(db_session, centre_a.id, end_offset=timedelta(minutes=-90))
    db_session.execute(
        delete(ProcurementSlot).where(
            ProcurementSlot.centre_id == centre_a.id, ProcurementSlot.id != only_slot.id
        )
    )
    # centre_b has a suitable future slot with spare capacity.
    alt_slot = make_slot(db_session, centre_b.id, end_offset=timedelta(hours=4), capacity=3)
    db_session.execute(
        delete(ProcurementSlot).where(
            ProcurementSlot.centre_id == centre_b.id, ProcurementSlot.id != alt_slot.id
        )
    )
    db_session.commit()

    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_a.id,
        slot_id=only_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "DELAYED"
    assert body["recommendation"] == "RECOMMEND_ALTERNATE_CENTRE"
    assert body["recommended_slot_id"] == alt_slot.id
    assert body["recommended_centre_id"] == centre_b.id


@pytest.mark.anyio
async def test_delayed_booking_with_no_alternative_warns_farmer(
    client: AsyncClient, db_session: Session
) -> None:
    centre_record = centre(db_session)
    deactivate_other_centres(db_session, keep_ids={centre_record.id})
    add_snapshot(db_session, centre_record.id, "12.50")

    only_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=-90))
    db_session.execute(
        delete(ProcurementSlot).where(
            ProcurementSlot.centre_id == centre_record.id,
            ProcurementSlot.id != only_slot.id,
        )
    )
    db_session.commit()

    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=only_slot.id,
    )

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["scheduling_status"] == "DELAYED"
    assert body["recommendation"] == "WARN_FARMER"
    assert body["recommended_slot_id"] is None
    assert body["recommended_centre_id"] is None


# --------------------------------------------------------------------------
# Centre assessment endpoint
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_centre_assessment_endpoint_lists_pending_bookings(
    client: AsyncClient, db_session: Session
) -> None:
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")

    response = await client.get(f"/api/scheduling/centres/{centre_record.id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    assert all(item["centre_id"] == centre_record.id for item in body)

    expected_ids = {
        b.id
        for b in db_session.scalars(
            select(Booking).where(
                Booking.centre_id == centre_record.id,
                Booking.status.in_(
                    (
                        BookingStatus.BOOKED,
                        BookingStatus.CHECKED_IN,
                        BookingStatus.IN_QUEUE,
                        BookingStatus.PROCESSING,
                    )
                ),
            )
        )
    }
    assert {item["booking_id"] for item in body} == expected_ids


# --------------------------------------------------------------------------
# No mutation guarantee
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_assessment_does_not_mutate_booking_or_slot_capacity(
    client: AsyncClient, db_session: Session
) -> None:
    centre_record = centre(db_session)
    add_snapshot(db_session, centre_record.id, "12.50")
    past_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(minutes=-90))
    future_slot = make_slot(db_session, centre_record.id, end_offset=timedelta(days=1))
    booking = make_booking(
        db_session,
        farmer_id=farmer(db_session).id,
        centre_id=centre_record.id,
        slot_id=past_slot.id,
    )

    before_status = booking.status
    before_past_capacity = past_slot.capacity
    before_future_capacity = future_slot.capacity

    response = await client.get(f"/api/scheduling/bookings/{booking.id}")
    assert response.status_code == 200
    assert response.json()["recommendation"] == "PROPOSE_NEW_SLOT"

    # Re-query fresh from the same underlying database file to be sure
    # nothing was flushed/committed by the assessment.
    refreshed_engine = create_engine(f"sqlite:///{db_session.get_bind().url.database}")
    refreshed_session = sessionmaker(bind=refreshed_engine)()
    try:
        refreshed_booking = refreshed_session.get(Booking, booking.id)
        refreshed_past_slot = refreshed_session.get(ProcurementSlot, past_slot.id)
        refreshed_future_slot = refreshed_session.get(ProcurementSlot, future_slot.id)
        assert refreshed_booking.status == before_status
        assert refreshed_past_slot.capacity == before_past_capacity
        assert refreshed_future_slot.capacity == before_future_capacity
    finally:
        refreshed_session.close()
        refreshed_engine.dispose()
