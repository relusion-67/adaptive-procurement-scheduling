from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed import seed_demo_data
from app.db.session import get_db
from app.main import app
from app.models import Booking, Farmer, ProcurementCentre, ProcurementSlot
from tests._auth_helpers import create_admin, auth_headers


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'booking_api.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_demo_data(session)
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
    admin = create_admin(db_session, email="booking-api-admin@example.test")
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


def demo_farmer(session: Session) -> Farmer:
    farmer = session.scalar(select(Farmer).where(Farmer.phone == "9000000001"))
    assert farmer is not None
    return farmer


def demo_centre(session: Session, code: str = "TNJ-CENTRAL-01") -> ProcurementCentre:
    centre = session.scalar(select(ProcurementCentre).where(ProcurementCentre.code == code))
    assert centre is not None
    return centre


def available_slot(session: Session, centre_id: int) -> ProcurementSlot:
    slot = session.scalar(
        select(ProcurementSlot)
        .where(
            ProcurementSlot.centre_id == centre_id,
            ProcurementSlot.capacity > 0,
        )
        .order_by(ProcurementSlot.id)
    )
    assert slot is not None
    return slot


def booking_payload(session: Session) -> dict[str, int | str | float]:
    farmer = demo_farmer(session)
    centre = demo_centre(session)
    slot = available_slot(session, centre.id)
    return {
        "farmer_id": farmer.id,
        "centre_id": centre.id,
        "slot_id": slot.id,
        "crop_type": "Paddy",
        "quantity_kg": 500,
    }


@pytest.mark.anyio
async def test_create_farmer(client: AsyncClient) -> None:
    response = await client.post(
        "/api/farmers/",
        json={"name": "S. Kavitha", "phone": "9000000099", "village": "Budalur"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "S. Kavitha"


@pytest.mark.anyio
async def test_list_farmers_endpoint_is_disabled(client: AsyncClient) -> None:
    response = await client.get("/api/farmers/")

    assert response.status_code == 405


@pytest.mark.anyio
async def test_list_active_centres(client: AsyncClient, db_session: Session) -> None:
    db_session.add(
        ProcurementCentre(
            name="Inactive Centre",
            code="INACTIVE-01",
            district="Thanjavur",
            daily_capacity=10,
            active=False,
        )
    )
    db_session.commit()

    response = await client.get("/api/centres/")

    assert response.status_code == 200
    assert [centre["code"] for centre in response.json()] == [
        "TNJ-CENTRAL-01",
        "KUM-01",
    ]


@pytest.mark.anyio
async def test_list_usable_slots_for_centre(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre = demo_centre(db_session)
    full_slot = available_slot(db_session, centre.id)
    full_slot.capacity = 0
    db_session.commit()

    response = await client.get(f"/api/centres/{centre.id}/slots")

    assert response.status_code == 200
    slots = response.json()
    assert len(slots) == 8
    assert all(slot["capacity"] > 0 for slot in slots)


@pytest.mark.anyio
async def test_create_booking_reserves_slot_capacity(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    slot = db_session.get(ProcurementSlot, payload["slot_id"])
    assert slot is not None
    original_capacity = slot.capacity

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "BOOKED"
    assert body["quantity_kg"] == "500.00"
    db_session.refresh(slot)
    assert slot.capacity == original_capacity - 1
    assert db_session.get(Booking, body["id"]) is not None


@pytest.mark.anyio
async def test_create_booking_rejects_nonexistent_farmer(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    payload["farmer_id"] = 99999

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Farmer not found"


@pytest.mark.anyio
async def test_create_booking_rejects_inactive_centre(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    centre = demo_centre(db_session)
    centre.active = False
    db_session.commit()

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Procurement centre is inactive"


@pytest.mark.anyio
async def test_create_booking_rejects_invalid_quantity(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    payload["quantity_kg"] = 0

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_create_booking_rejects_nonexistent_slot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    payload["slot_id"] = 99999

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Procurement slot not found"


@pytest.mark.anyio
async def test_create_booking_rejects_centre_slot_mismatch(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    other_centre = demo_centre(db_session, "KUM-01")
    other_slot = available_slot(db_session, other_centre.id)
    payload["slot_id"] = other_slot.id

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Procurement slot does not belong to the selected centre"


@pytest.mark.anyio
async def test_create_booking_rejects_expired_slot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    slot = db_session.get(ProcurementSlot, payload["slot_id"])
    assert slot is not None

    original_capacity = slot.capacity
    booking_count_before = len(
        db_session.scalars(
            select(Booking).where(Booking.slot_id == slot.id)
        ).all()
    )

    slot.slot_date = datetime(2020, 1, 1).date()
    slot.start_time = time(9, 0)
    slot.end_time = time(10, 0)
    db_session.commit()

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Procurement slot has expired"

    db_session.refresh(slot)
    assert slot.capacity == original_capacity

    booking_count_after = len(
        db_session.scalars(
            select(Booking).where(Booking.slot_id == slot.id)
        ).all()
    )
    assert booking_count_after == booking_count_before


@pytest.mark.anyio
async def test_create_booking_rejects_full_slot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    payload = booking_payload(db_session)
    slot = db_session.get(ProcurementSlot, payload["slot_id"])
    assert slot is not None
    slot.capacity = 0
    db_session.commit()

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Procurement slot is full"


@pytest.mark.anyio
async def test_get_booking(client: AsyncClient, db_session: Session) -> None:
    booking = db_session.scalar(select(Booking).order_by(Booking.id))
    assert booking is not None

    response = await client.get(f"/api/bookings/{booking.id}")

    assert response.status_code == 200
    assert response.json()["id"] == booking.id


@pytest.mark.anyio
async def test_get_booking_rejects_unknown_booking(client: AsyncClient) -> None:
    response = await client.get("/api/bookings/99999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Booking not found"
