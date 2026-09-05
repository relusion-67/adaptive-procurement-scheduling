from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import ProcurementCentre, ProcurementSlot
from app.repositories import procurement as procurement_repository


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'procurement_repository.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        command.downgrade(alembic_cfg, "base")


def make_centre(session: Session) -> ProcurementCentre:
    centre = ProcurementCentre(
        name="Test Centre",
        code="TEST-01",
        district="Test District",
        daily_capacity=100,
    )
    session.add(centre)
    session.commit()
    session.refresh(centre)
    return centre


def make_slot(
    session: Session,
    centre_id: int,
    *,
    start: datetime,
    duration: timedelta = timedelta(hours=1),
    capacity: int = 5,
) -> ProcurementSlot:
    end = start + duration
    slot = ProcurementSlot(
        centre_id=centre_id,
        slot_date=start.date(),
        start_time=start.time(),
        end_time=end.time(),
        capacity=capacity,
    )
    session.add(slot)
    session.commit()
    session.refresh(slot)
    return slot


def test_expired_slot_is_excluded(db_session: Session) -> None:
    centre = make_centre(db_session)
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

    expired_slot = make_slot(db_session, centre.id, start=now - timedelta(hours=3))

    usable = procurement_repository.list_usable_slots(db_session, centre.id, now=now)

    assert expired_slot.id not in {slot.id for slot in usable}


def test_slot_later_today_remains_visible(db_session: Session) -> None:
    centre = make_centre(db_session)
    now = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)

    later_today_slot = make_slot(db_session, centre.id, start=now + timedelta(hours=2))

    usable = procurement_repository.list_usable_slots(db_session, centre.id, now=now)

    assert later_today_slot.id in {slot.id for slot in usable}


def test_slot_currently_in_progress_remains_visible(db_session: Session) -> None:
    """A slot whose window straddles `now` (started but not yet ended)
    should still be usable - only fully elapsed slots are excluded."""
    centre = make_centre(db_session)
    now = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)

    in_progress_slot = make_slot(
        db_session, centre.id, start=now - timedelta(minutes=15), duration=timedelta(hours=1)
    )

    usable = procurement_repository.list_usable_slots(db_session, centre.id, now=now)

    assert in_progress_slot.id in {slot.id for slot in usable}


def test_slot_on_future_day_remains_visible(db_session: Session) -> None:
    centre = make_centre(db_session)
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

    future_day_slot = make_slot(db_session, centre.id, start=now + timedelta(days=2))

    usable = procurement_repository.list_usable_slots(db_session, centre.id, now=now)

    assert future_day_slot.id in {slot.id for slot in usable}


def test_zero_capacity_slot_is_still_excluded(db_session: Session) -> None:
    """Existing capacity-based filtering keeps working alongside the new
    expiry filtering."""
    centre = make_centre(db_session)
    now = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)

    full_slot = make_slot(
        db_session, centre.id, start=now + timedelta(hours=2), capacity=0
    )

    usable = procurement_repository.list_usable_slots(db_session, centre.id, now=now)

    assert full_slot.id not in {slot.id for slot in usable}


def test_defaults_to_current_time_when_now_not_provided(db_session: Session) -> None:
    centre = make_centre(db_session)

    long_past_slot = make_slot(
        db_session, centre.id, start=datetime(2020, 1, 1, 9, 0, tzinfo=timezone.utc)
    )
    far_future_slot = make_slot(
        db_session, centre.id, start=datetime(2099, 1, 1, 9, 0, tzinfo=timezone.utc)
    )

    usable_ids = {
        slot.id for slot in procurement_repository.list_usable_slots(db_session, centre.id)
    }

    assert long_past_slot.id not in usable_ids
    assert far_future_slot.id in usable_ids
