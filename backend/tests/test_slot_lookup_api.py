"""Regression tests for Audit Finding 1.

Bug: an existing booking's slot disappeared from frontend context once the
slot's remaining capacity reached 0, because the only slot-fetching
endpoint available (GET /api/centres/{id}/slots -> list_usable_slots)
intentionally excludes full slots to keep NEW-booking discovery clean.

Fix: GET /api/slots/{slot_id} performs a direct lookup and returns the slot
regardless of remaining capacity, while list_usable_slots() (exercised via
GET /api/centres/{id}/slots) keeps hiding full/expired slots for new
bookings.
"""

from __future__ import annotations

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
from app.models import Farmer, ProcurementCentre, ProcurementSlot
from tests._auth_helpers import auth_headers, create_admin


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'slot_lookup.sqlite3'}"
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
    admin = create_admin(db_session, email="test_slot_lookup_api-admin@example.test")
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
async def test_get_slot_returns_available_slot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    centre = demo_centre(db_session)
    slot = available_slot(db_session, centre.id)

    response = await client.get(f"/api/slots/{slot.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == slot.id
    assert body["centre_id"] == centre.id
    assert body["capacity"] > 0


@pytest.mark.anyio
async def test_get_slot_returns_full_slot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """A slot at capacity 0 must still be retrievable by direct id lookup."""
    centre = demo_centre(db_session)
    slot = available_slot(db_session, centre.id)
    slot.capacity = 0
    db_session.commit()

    response = await client.get(f"/api/slots/{slot.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == slot.id
    assert body["capacity"] == 0
    # Date/time metadata must still be present so the frontend can render it.
    assert body["slot_date"] == slot.slot_date.isoformat()
    assert body["start_time"] is not None
    assert body["end_time"] is not None


@pytest.mark.anyio
async def test_get_slot_unknown_id_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/slots/999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Procurement slot not found"


@pytest.mark.anyio
async def test_full_slot_still_excluded_from_usable_listing(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """list_usable_slots()/GET /api/centres/{id}/slots must keep hiding full
    slots from NEW-booking discovery even though direct lookup now works."""
    centre = demo_centre(db_session)
    slot = available_slot(db_session, centre.id)
    slot.capacity = 0
    db_session.commit()

    response = await client.get(f"/api/centres/{centre.id}/slots")

    assert response.status_code == 200
    listed_ids = {s["id"] for s in response.json()}
    assert slot.id not in listed_ids
    assert all(s["capacity"] > 0 for s in response.json())


@pytest.mark.anyio
async def test_available_slots_remain_bookable(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Sanity check: booking flow for a non-full slot is unaffected."""
    payload = booking_payload(db_session)

    response = await client.post("/api/bookings/", json=payload)

    assert response.status_code == 201
    assert response.json()["status"] == "BOOKED"


@pytest.mark.anyio
async def test_existing_booking_slot_metadata_survives_slot_filling_up(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """End-to-end regression for Finding 1: create a booking, let its slot
    fill up (capacity reaches 0), and confirm the slot's date/time is still
    retrievable via the booking's slot_id - proving confirmation/tracking
    screens (which chain GET booking -> GET slot) keep working."""
    payload = booking_payload(db_session)
    create_response = await client.post("/api/bookings/", json=payload)
    assert create_response.status_code == 201
    booking = create_response.json()

    slot = db_session.get(ProcurementSlot, booking["slot_id"])
    assert slot is not None
    slot.capacity = 0
    db_session.commit()

    # Confirmation/tracking flow: fetch the booking, then its slot directly.
    booking_response = await client.get(f"/api/bookings/{booking['id']}")
    assert booking_response.status_code == 200
    slot_id = booking_response.json()["slot_id"]

    slot_response = await client.get(f"/api/slots/{slot_id}")
    assert slot_response.status_code == 200
    slot_body = slot_response.json()
    assert slot_body["slot_date"] == slot.slot_date.isoformat()
    assert slot_body["capacity"] == 0


@pytest.mark.anyio
async def test_adaptive_status_renders_for_full_booked_slot(
    client: AsyncClient,
    db_session: Session,
) -> None:
    """Adaptive scheduling assessment must keep working for a booking whose
    slot has since filled up - Finding 1 must not touch adaptive logic."""
    payload = booking_payload(db_session)
    create_response = await client.post("/api/bookings/", json=payload)
    assert create_response.status_code == 201
    booking = create_response.json()

    slot = db_session.get(ProcurementSlot, booking["slot_id"])
    assert slot is not None
    slot.capacity = 0
    db_session.commit()

    response = await client.get(f"/api/scheduling/bookings/{booking['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["booking_id"] == booking["id"]
    assert body["scheduling_status"] in {"ON_TRACK", "AT_RISK", "DELAYED"}
