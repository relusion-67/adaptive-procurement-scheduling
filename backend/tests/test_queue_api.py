from __future__ import annotations

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
from app.models import Booking, BookingStatus, ProcurementCentre, QueueEntry, QueueStatus
from tests._auth_helpers import auth_headers, create_admin


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'queue_api.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session)
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
    admin = create_admin(db_session, email="test_queue_api-admin@example.test")
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


@pytest.mark.anyio
async def test_check_in_creates_waiting_queue_entry_and_syncs_booking(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)

    body = await check_in(client, booking)

    assert body["token_number"] == 1
    assert body["queue_status"] == "WAITING"
    db_session.refresh(booking)
    assert booking.status == BookingStatus.IN_QUEUE


@pytest.mark.anyio
async def test_duplicate_check_in_is_rejected(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    await check_in(client, booking)

    response = await client.post(
        "/api/queue/check-in",
        json={"booking_id": booking.id, "centre_id": booking.centre_id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Booking already has a queue entry"


@pytest.mark.anyio
async def test_check_in_rejects_booking_from_another_centre(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    other_centre = centre(db_session, "KUM-01")

    response = await client.post(
        "/api/queue/check-in",
        json={"booking_id": booking.id, "centre_id": other_centre.id},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Booking does not belong to the selected centre"


@pytest.mark.anyio
async def test_check_in_rejects_invalid_booking_state(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    booking.status = BookingStatus.CANCELLED
    db_session.commit()

    response = await client.post(
        "/api/queue/check-in",
        json={"booking_id": booking.id, "centre_id": booking.centre_id},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Booking is not eligible for check-in"


@pytest.mark.anyio
async def test_tokens_are_unique_within_a_centre(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    first_booking = booked_booking(db_session, centre_record.id)
    second_booking = booked_booking(db_session, centre_record.id, offset=1)

    first_entry = await check_in(client, first_booking)
    second_entry = await check_in(client, second_booking)

    assert {first_entry["token_number"], second_entry["token_number"]} == {1, 2}


@pytest.mark.anyio
async def test_live_queue_returns_operational_order(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre_record = centre(db_session)
    first_booking = booked_booking(db_session, centre_record.id)
    second_booking = booked_booking(db_session, centre_record.id, offset=1)
    first_entry = await check_in(client, first_booking)
    second_entry = await check_in(client, second_booking)
    call_response = await client.post(f"/api/queue/centres/{centre_record.id}/call-next")
    assert call_response.status_code == 200

    response = await client.get(f"/api/queue/centres/{centre_record.id}")

    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()] == [
        first_entry["id"],
        second_entry["id"],
    ]
    assert [entry["queue_status"] for entry in response.json()] == ["CALLED", "WAITING"]


@pytest.mark.anyio
async def test_call_next_farmer(client: AsyncClient, db_session: Session) -> None:
    centre_record = centre(db_session)
    booking = booked_booking(db_session, centre_record.id)
    entry = await check_in(client, booking)

    response = await client.post(f"/api/queue/centres/{centre_record.id}/call-next")

    assert response.status_code == 200
    assert response.json()["id"] == entry["id"]
    assert response.json()["queue_status"] == "CALLED"
    db_session.refresh(booking)
    assert booking.status == BookingStatus.IN_QUEUE


@pytest.mark.anyio
async def test_start_serving_syncs_booking_status(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    entry = await check_in(client, booking)
    await client.post(f"/api/queue/centres/{booking.centre_id}/call-next")

    response = await client.post(f"/api/queue/{entry['id']}/start-serving")

    assert response.status_code == 200
    assert response.json()["queue_status"] == "SERVING"
    db_session.refresh(booking)
    assert booking.status == BookingStatus.PROCESSING


@pytest.mark.anyio
async def test_complete_service_syncs_booking_status(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    entry = await check_in(client, booking)
    await client.post(f"/api/queue/centres/{booking.centre_id}/call-next")
    await client.post(f"/api/queue/{entry['id']}/start-serving")

    response = await client.post(f"/api/queue/{entry['id']}/complete")

    assert response.status_code == 200
    assert response.json()["queue_status"] == "DONE"
    db_session.refresh(booking)
    assert booking.status == BookingStatus.COMPLETED


@pytest.mark.anyio
async def test_mark_no_show_syncs_booking_status(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    entry = await check_in(client, booking)

    response = await client.post(f"/api/queue/{entry['id']}/no-show")

    assert response.status_code == 200
    assert response.json()["queue_status"] == "NO_SHOW"
    db_session.refresh(booking)
    assert booking.status == BookingStatus.MISSED


@pytest.mark.anyio
async def test_invalid_queue_transition_is_rejected(
    client: AsyncClient,
    db_session: Session,
) -> None:
    booking = booked_booking(db_session, centre(db_session).id)
    entry = await check_in(client, booking)

    response = await client.post(f"/api/queue/{entry['id']}/complete")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot transition queue entry from WAITING to DONE"
