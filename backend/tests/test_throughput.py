from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, func, select, update
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
from app.repositories import throughput as throughput_repository
from app.services import throughput as throughput_service
from tests._auth_helpers import auth_headers, create_admin


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'throughput.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session)
    # Start from a clean queue/booking/throughput state so the throughput
    # math in each test is deterministic and doesn't depend on the fixed
    # demo queue entries or the seeded snapshot.
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
    admin = create_admin(db_session, email="test_throughput-admin@example.test")
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


def centre(session: Session, code: str = "TNJ-CENTRAL-01") -> ProcurementCentre:
    result = session.scalar(select(ProcurementCentre).where(ProcurementCentre.code == code))
    assert result is not None
    return result


def bookings_for_centre(
    session: Session,
    centre: ProcurementCentre,
    minimum: int = 3,
) -> list[Booking]:
    """Return the centre's existing bookings, synthesizing extra ones (reusing
    an existing farmer and slot) if the fixed demo dataset doesn't have
    enough for a given test's sample size. These tests only care about
    queue-entry timing, not booking content, so reuse is fine."""
    bookings = list(
        session.scalars(
            select(Booking).where(Booking.centre_id == centre.id).order_by(Booking.id)
        )
    )
    if len(bookings) >= minimum:
        return bookings

    farmer = session.scalars(select(Farmer)).first()
    assert farmer is not None
    slot = session.scalar(
        select(ProcurementSlot).where(ProcurementSlot.centre_id == centre.id)
    )
    assert slot is not None
    while len(bookings) < minimum:
        booking = Booking(
            farmer_id=farmer.id,
            centre_id=centre.id,
            slot_id=slot.id,
            crop_type="Paddy",
            quantity_kg=Decimal("100.00"),
            status=BookingStatus.BOOKED,
        )
        session.add(booking)
        session.flush()
        bookings.append(booking)
    return bookings


def make_completed_entry(
    session: Session,
    centre_id: int,
    booking_id: int,
    token_number: int,
    served_at: datetime,
) -> QueueEntry:
    """Directly create a DONE queue entry with a specific served_at, so
    throughput math can be tested against known, controlled timestamps
    instead of the live wall clock."""
    entry = QueueEntry(
        centre_id=centre_id,
        booking_id=booking_id,
        token_number=token_number,
        queue_status=QueueStatus.DONE,
        checked_in_at=served_at - timedelta(minutes=5),
        called_at=served_at - timedelta(minutes=2),
        served_at=served_at,
    )
    session.add(entry)
    session.flush()
    return entry


# ---------------------------------------------------------------------------
# Service-layer: calculate_average_service_minutes
# ---------------------------------------------------------------------------


def test_calculate_average_returns_none_when_no_completed_entries(
    db_session: Session,
) -> None:
    centre_record = centre(db_session)

    result = throughput_service.calculate_average_service_minutes(
        db_session, centre_record.id
    )

    assert result is None


def test_calculate_average_returns_none_below_minimum_sample_size(
    db_session: Session,
) -> None:
    """Two completions produce a single interval, which is one short of the
    minimum this engine trusts enough to persist."""
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record)
    base = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, base)
    make_completed_entry(
        db_session, centre_record.id, bookings[1].id, 2, base + timedelta(minutes=10)
    )
    db_session.commit()

    result = throughput_service.calculate_average_service_minutes(
        db_session, centre_record.id
    )

    assert result is None


def test_calculate_average_normal_case(db_session: Session) -> None:
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record)
    base = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    # Service starts 10, then 12 minutes apart -> average 11.00 minutes.
    make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, base)
    make_completed_entry(
        db_session, centre_record.id, bookings[1].id, 2, base + timedelta(minutes=10)
    )
    make_completed_entry(
        db_session, centre_record.id, bookings[2].id, 3, base + timedelta(minutes=22)
    )
    db_session.commit()

    result = throughput_service.calculate_average_service_minutes(
        db_session, centre_record.id
    )

    assert result == Decimal("11.00")


def test_calculate_average_ignores_gaps_crossing_calendar_dates(
    db_session: Session,
) -> None:
    """An overnight gap between the last service of one day and the first of
    the next shouldn't be treated as a 15-hour service time."""
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record, minimum=4)
    day_one = datetime(2026, 11, 2, 17, 50, tzinfo=timezone.utc)
    day_one_next = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)  # +10 min, same day
    day_two = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)  # overnight gap, dropped
    day_two_next = datetime(2026, 11, 3, 9, 8, tzinfo=timezone.utc)  # +8 min, same day

    make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, day_one)
    make_completed_entry(db_session, centre_record.id, bookings[1].id, 2, day_one_next)
    make_completed_entry(db_session, centre_record.id, bookings[2].id, 3, day_two)
    make_completed_entry(db_session, centre_record.id, bookings[3].id, 4, day_two_next)
    db_session.commit()

    result = throughput_service.calculate_average_service_minutes(
        db_session, centre_record.id
    )

    # Only the 10-minute and 8-minute same-day gaps count -> average 9.00.
    assert result == Decimal("9.00")


def test_calculate_average_uses_bounded_recent_window(db_session: Session) -> None:
    """Very old history shouldn't dilute a centre's current pace forever;
    only the most recent RECALCULATION_LOOKBACK_LIMIT completions count."""
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record, minimum=4)
    # Not enough distinct seeded bookings to reach the real lookback limit
    # without changing seed data, so temporarily shrink it for this test.
    original_limit = throughput_service.RECALCULATION_LOOKBACK_LIMIT
    throughput_service.RECALCULATION_LOOKBACK_LIMIT = 3
    try:
        base = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
        # An old, huge 500-minute gap that must be excluded by the window...
        make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, base)
        make_completed_entry(
            db_session,
            centre_record.id,
            bookings[1].id,
            2,
            base + timedelta(minutes=500),
        )
        # ...followed by a consistent recent 5-minute pace.
        make_completed_entry(
            db_session,
            centre_record.id,
            bookings[2].id,
            3,
            base + timedelta(minutes=505),
        )
        make_completed_entry(
            db_session,
            centre_record.id,
            bookings[3].id,
            4,
            base + timedelta(minutes=510),
        )
        db_session.commit()

        result = throughput_service.calculate_average_service_minutes(
            db_session, centre_record.id
        )
    finally:
        throughput_service.RECALCULATION_LOOKBACK_LIMIT = original_limit

    # With window=3, only the last 3 completions are considered, giving a
    # single clean 5-minute gap rather than being dragged up by the 500.
    assert result == Decimal("5.00")


# ---------------------------------------------------------------------------
# Service-layer: recalculate_throughput / recalculate_throughput_for_centre
# ---------------------------------------------------------------------------


def test_recalculate_throughput_persists_snapshot_when_data_is_sufficient(
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record)
    base = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, base)
    make_completed_entry(
        db_session, centre_record.id, bookings[1].id, 2, base + timedelta(minutes=6)
    )
    make_completed_entry(
        db_session, centre_record.id, bookings[2].id, 3, base + timedelta(minutes=12)
    )
    db_session.commit()

    snapshot = throughput_service.recalculate_throughput(db_session, centre_record.id)

    assert snapshot is not None
    assert snapshot.centre_id == centre_record.id
    assert snapshot.avg_minutes_per_farmer == Decimal("6.00")

    latest = throughput_repository.get_latest_snapshot(db_session, centre_record.id)
    assert latest is not None
    assert latest.id == snapshot.id


def test_recalculate_throughput_does_not_persist_when_insufficient_data(
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    before_count = db_session.scalar(
        select(func.count()).select_from(ThroughputSnapshot)
    )

    result = throughput_service.recalculate_throughput(db_session, centre_record.id)

    assert result is None
    after_count = db_session.scalar(select(func.count()).select_from(ThroughputSnapshot))
    assert after_count == before_count


def test_recalculate_throughput_for_centre_raises_for_unknown_centre(
    db_session: Session,
) -> None:
    with pytest.raises(throughput_service.ThroughputError) as exc_info:
        throughput_service.recalculate_throughput_for_centre(db_session, 999999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Procurement centre not found"


def test_recalculate_throughput_for_centre_raises_when_insufficient_data(
    db_session: Session,
) -> None:
    centre_record = centre(db_session)

    with pytest.raises(throughput_service.ThroughputError) as exc_info:
        throughput_service.recalculate_throughput_for_centre(db_session, centre_record.id)

    assert exc_info.value.status_code == 409
    assert "Insufficient" in exc_info.value.detail


# ---------------------------------------------------------------------------
# API: queue completion feeds the throughput engine automatically
# ---------------------------------------------------------------------------


async def _run_full_queue_cycle(client: AsyncClient, booking: Booking) -> None:
    check_in_response = await client.post(
        "/api/queue/check-in",
        json={"booking_id": booking.id, "centre_id": booking.centre_id},
    )
    assert check_in_response.status_code == 201, check_in_response.text
    entry_id = check_in_response.json()["id"]

    call_response = await client.post(f"/api/queue/centres/{booking.centre_id}/call-next")
    assert call_response.status_code == 200, call_response.text

    start_response = await client.post(f"/api/queue/{entry_id}/start-serving")
    assert start_response.status_code == 200, start_response.text

    complete_response = await client.post(f"/api/queue/{entry_id}/complete")
    assert complete_response.status_code == 200, complete_response.text


@pytest.mark.anyio
async def test_third_completion_automatically_creates_throughput_snapshot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record)
    assert len(bookings) >= 3

    for booking in bookings[:2]:
        await _run_full_queue_cycle(client, booking)

    # Only two completions so far: still insufficient for a snapshot.
    assert (
        throughput_repository.get_latest_snapshot(db_session, centre_record.id) is None
    )

    await _run_full_queue_cycle(client, bookings[2])

    snapshot = throughput_repository.get_latest_snapshot(db_session, centre_record.id)
    assert snapshot is not None
    assert snapshot.centre_id == centre_record.id
    assert snapshot.avg_minutes_per_farmer >= Decimal("0.00")


# ---------------------------------------------------------------------------
# API: admin throughput endpoints
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_latest_throughput_returns_404_when_none_exists(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)

    response = await client.get(f"/api/admin/throughput/{centre_record.id}")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "No throughput snapshot is available for this centre yet"
    )


@pytest.mark.anyio
async def test_get_latest_throughput_returns_persisted_snapshot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record)
    base = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, base)
    make_completed_entry(
        db_session, centre_record.id, bookings[1].id, 2, base + timedelta(minutes=8)
    )
    make_completed_entry(
        db_session, centre_record.id, bookings[2].id, 3, base + timedelta(minutes=16)
    )
    db_session.commit()
    throughput_service.recalculate_throughput(db_session, centre_record.id)

    response = await client.get(f"/api/admin/throughput/{centre_record.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["centre_id"] == centre_record.id
    assert Decimal(body["avg_minutes_per_farmer"]) == Decimal("8.00")


@pytest.mark.anyio
async def test_recalculate_throughput_endpoint_rejects_unknown_centre(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/admin/throughput/999999/recalculate")

    assert response.status_code == 404
    assert response.json()["detail"] == "Procurement centre not found"


@pytest.mark.anyio
async def test_recalculate_throughput_endpoint_reports_insufficient_data(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)

    response = await client.post(f"/api/admin/throughput/{centre_record.id}/recalculate")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Insufficient completed queue history to calculate throughput for "
        "this centre"
    )


@pytest.mark.anyio
async def test_recalculate_throughput_endpoint_returns_new_snapshot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    bookings = bookings_for_centre(db_session, centre_record)
    base = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    make_completed_entry(db_session, centre_record.id, bookings[0].id, 1, base)
    make_completed_entry(
        db_session, centre_record.id, bookings[1].id, 2, base + timedelta(minutes=5)
    )
    make_completed_entry(
        db_session, centre_record.id, bookings[2].id, 3, base + timedelta(minutes=10)
    )
    db_session.commit()

    response = await client.post(f"/api/admin/throughput/{centre_record.id}/recalculate")

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["avg_minutes_per_farmer"]) == Decimal("5.00")

    latest = throughput_repository.get_latest_snapshot(db_session, centre_record.id)
    assert latest is not None
    assert latest.avg_minutes_per_farmer == Decimal("5.00")
