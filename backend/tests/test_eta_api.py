from __future__ import annotations

from datetime import datetime, timezone
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
    ProcurementCentre,
    QueueEntry,
    QueueStatus,
    ThroughputSnapshot,
)
from app.services.eta import DEFAULT_AVERAGE_SERVICE_MINUTES
from tests._auth_helpers import auth_headers, create_admin


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'eta_api.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session)
    # Start from a clean queue/booking state for each test so ETA math is
    # deterministic and doesn't depend on the fixed demo queue entries.
    session.execute(delete(QueueEntry))
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
    admin = create_admin(db_session, email="test_eta_api-admin@example.test")
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


def booked_booking(session: Session, centre_id: int, offset: int = 0) -> Booking:
    bookings = list(
        session.scalars(
            select(Booking)
            .where(
                Booking.centre_id == centre_id,
                Booking.status == BookingStatus.BOOKED,
            )
            .order_by(Booking.id)
        )
    )
    assert len(bookings) > offset
    return bookings[offset]


async def check_in(client: AsyncClient, booking: Booking) -> dict[str, object]:
    response = await client.post(
        "/api/queue/check-in",
        json={"booking_id": booking.id, "centre_id": booking.centre_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def latest_snapshot_minutes(session: Session, centre_id: int) -> Decimal:
    snapshot = session.scalar(
        select(ThroughputSnapshot)
        .where(ThroughputSnapshot.centre_id == centre_id)
        .order_by(ThroughputSnapshot.snapshot_at.desc(), ThroughputSnapshot.id.desc())
    )
    assert snapshot is not None
    return Decimal(snapshot.avg_minutes_per_farmer)


@pytest.mark.anyio
async def test_eta_for_first_in_queue_has_zero_wait(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    booking = booked_booking(db_session, centre_record.id)
    entry = await check_in(client, booking)

    response = await client.get(f"/api/queue/{entry['id']}/eta")

    assert response.status_code == 200
    body = response.json()
    assert body["queue_entry_id"] == entry["id"]
    assert body["token_number"] == entry["token_number"]
    assert body["queue_position"] == 1
    assert body["farmers_ahead"] == 0
    assert Decimal(body["estimated_wait_minutes"]) == Decimal("0.00")
    assert body["queue_status"] == "WAITING"
    # Sanity check the timestamp is well-formed and recent.
    datetime.fromisoformat(body["calculated_at"].replace("Z", "+00:00"))


@pytest.mark.anyio
async def test_eta_with_multiple_farmers_ahead(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """A target entry with 2 farmers genuinely ahead of it, across a realistic
    mix of SERVING/CALLED/WAITING states, exercising the existing operational
    priority ordering (SERVING before CALLED before WAITING) rather than just
    token order."""
    centre_record = centre(db_session)
    first_booking = booked_booking(db_session, centre_record.id)
    second_booking = booked_booking(db_session, centre_record.id, offset=1)
    third_booking = booked_booking(db_session, centre_record.id, offset=2)
    first_entry = await check_in(client, first_booking)
    second_entry = await check_in(client, second_booking)
    third_entry = await check_in(client, third_booking)

    # Move the first entry all the way to SERVING, and call the second entry
    # up to CALLED, leaving the third entry WAITING behind both of them.
    call_response = await client.post(f"/api/queue/centres/{centre_record.id}/call-next")
    assert call_response.status_code == 200
    assert call_response.json()["id"] == first_entry["id"]

    serving_response = await client.post(f"/api/queue/{first_entry['id']}/start-serving")
    assert serving_response.status_code == 200
    assert serving_response.json()["queue_status"] == "SERVING"

    call_response = await client.post(f"/api/queue/centres/{centre_record.id}/call-next")
    assert call_response.status_code == 200
    assert call_response.json()["id"] == second_entry["id"]
    assert call_response.json()["queue_status"] == "CALLED"

    # Sanity-check the actual live-queue ordering the ETA calculation will
    # rely on: SERVING first, then CALLED, then WAITING.
    live_queue_response = await client.get(f"/api/queue/centres/{centre_record.id}")
    assert [e["id"] for e in live_queue_response.json()] == [
        first_entry["id"],
        second_entry["id"],
        third_entry["id"],
    ]
    assert [e["queue_status"] for e in live_queue_response.json()] == [
        "SERVING",
        "CALLED",
        "WAITING",
    ]

    expected_avg = latest_snapshot_minutes(db_session, centre_record.id)

    response = await client.get(f"/api/queue/{third_entry['id']}/eta")

    assert response.status_code == 200
    body = response.json()
    assert body["farmers_ahead"] == 2
    assert body["queue_position"] == 3
    assert Decimal(body["average_service_minutes"]) == expected_avg
    assert Decimal(body["estimated_wait_minutes"]) == expected_avg * 2
    assert body["queue_status"] == "WAITING"

    # The entry currently being served should show zero farmers ahead of it.
    first_response = await client.get(f"/api/queue/{first_entry['id']}/eta")
    assert first_response.json()["farmers_ahead"] == 0
    assert first_response.json()["queue_status"] == "SERVING"

    # The CALLED entry has exactly the SERVING entry ahead of it.
    second_response = await client.get(f"/api/queue/{second_entry['id']}/eta")
    assert second_response.json()["farmers_ahead"] == 1
    assert second_response.json()["queue_status"] == "CALLED"


@pytest.mark.anyio
async def test_eta_uses_latest_throughput_snapshot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    first_booking = booked_booking(db_session, centre_record.id)
    second_booking = booked_booking(db_session, centre_record.id, offset=1)
    await check_in(client, first_booking)
    second_entry = await check_in(client, second_booking)

    # Add a newer snapshot with a different value; the ETA should reflect this
    # one rather than the older seeded snapshot. The seed data's snapshot is
    # timestamped 2026-10-01, so we pick a date clearly after that instead of
    # relying on the wall clock.
    newer_snapshot = ThroughputSnapshot(
        centre_id=centre_record.id,
        snapshot_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        avg_minutes_per_farmer=Decimal("9.00"),
    )
    db_session.add(newer_snapshot)
    db_session.commit()

    response = await client.get(f"/api/queue/{second_entry['id']}/eta")

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["average_service_minutes"]) == Decimal("9.00")
    assert Decimal(body["estimated_wait_minutes"]) == Decimal("9.00")


@pytest.mark.anyio
async def test_eta_falls_back_when_no_throughput_history(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    # Remove all throughput history for this centre to force the fallback path.
    db_session.execute(
        delete(ThroughputSnapshot).where(ThroughputSnapshot.centre_id == centre_record.id)
    )
    db_session.commit()

    first_booking = booked_booking(db_session, centre_record.id)
    second_booking = booked_booking(db_session, centre_record.id, offset=1)
    await check_in(client, first_booking)
    second_entry = await check_in(client, second_booking)

    response = await client.get(f"/api/queue/{second_entry['id']}/eta")

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["average_service_minutes"]) == DEFAULT_AVERAGE_SERVICE_MINUTES
    assert Decimal(body["estimated_wait_minutes"]) == DEFAULT_AVERAGE_SERVICE_MINUTES * 1


@pytest.mark.anyio
async def test_eta_for_unknown_queue_entry_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/queue/999999/eta")

    assert response.status_code == 404
    assert response.json()["detail"] == "Queue entry not found"


@pytest.mark.anyio
async def test_eta_for_completed_queue_entry_is_rejected(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    entry = await check_in(client, booking)
    await client.post(f"/api/queue/centres/{booking.centre_id}/call-next")
    await client.post(f"/api/queue/{entry['id']}/start-serving")
    await client.post(f"/api/queue/{entry['id']}/complete")

    response = await client.get(f"/api/queue/{entry['id']}/eta")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Cannot calculate ETA for a queue entry with status DONE"
    )


@pytest.mark.anyio
async def test_eta_for_no_show_queue_entry_is_rejected(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    entry = await check_in(client, booking)
    await client.post(f"/api/queue/{entry['id']}/no-show")

    response = await client.get(f"/api/queue/{entry['id']}/eta")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Cannot calculate ETA for a queue entry with status NO_SHOW"
    )
