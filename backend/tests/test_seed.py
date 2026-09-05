from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.seed import DEMO_DAY_OFFSETS, _demo_dates, seed_demo_data
from app.models import (
    Booking,
    Farmer,
    NotificationLog,
    ProcurementCentre,
    ProcurementSlot,
    QueueEntry,
    ThroughputSnapshot,
)

EXPECTED_COUNTS = {
    "centres": 2,
    "farmers": 5,
    "slots": 18,
    "bookings": 5,
    "queue_entries": 3,
    "throughput_snapshots": 2,
    "notification_logs": 2,
}


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'seed.sqlite3'}"
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


def test_seed_creates_expected_demo_records(db_session: Session) -> None:
    assert seed_demo_data(db_session) == EXPECTED_COUNTS


def test_seed_is_idempotent(db_session: Session) -> None:
    seed_demo_data(db_session)
    first_counts = {
        "centres": db_session.scalar(select(func.count()).select_from(ProcurementCentre)),
        "farmers": db_session.scalar(select(func.count()).select_from(Farmer)),
        "slots": db_session.scalar(select(func.count()).select_from(ProcurementSlot)),
        "bookings": db_session.scalar(select(func.count()).select_from(Booking)),
        "queue_entries": db_session.scalar(select(func.count()).select_from(QueueEntry)),
        "throughput_snapshots": db_session.scalar(
            select(func.count()).select_from(ThroughputSnapshot)
        ),
        "notification_logs": db_session.scalar(
            select(func.count()).select_from(NotificationLog)
        ),
    }

    assert seed_demo_data(db_session) == first_counts == EXPECTED_COUNTS


def test_seeded_foreign_key_relationships_are_valid(db_session: Session) -> None:
    seed_demo_data(db_session)

    for booking in db_session.scalars(select(Booking)).all():
        assert booking.farmer is not None
        assert booking.centre is not None
        assert booking.slot is not None
        assert booking.slot.centre_id == booking.centre_id

    for queue_entry in db_session.scalars(select(QueueEntry)).all():
        assert queue_entry.booking is not None
        assert queue_entry.centre is not None
        assert queue_entry.booking.centre_id == queue_entry.centre_id

    for snapshot in db_session.scalars(select(ThroughputSnapshot)).all():
        assert snapshot.centre is not None

    for notification in db_session.scalars(select(NotificationLog)).all():
        assert notification.booking is not None


# --------------------------------------------------------------------------
# Rolling demo-date behaviour
# --------------------------------------------------------------------------


def test_demo_dates_are_relative_to_today_not_hardcoded() -> None:
    """`_demo_dates` must derive its dates from the supplied reference date
    rather than any fixed calendar date, so the seed stays usable forever."""
    reference = date(2031, 3, 17)  # arbitrary future date, well past 2026-10
    dates = _demo_dates(reference)

    assert dates == tuple(reference + timedelta(days=offset) for offset in DEMO_DAY_OFFSETS)
    # None of the generated dates should be in the past relative to the
    # reference date used to generate them.
    assert all(d > reference for d in dates)


def test_demo_dates_track_an_arbitrary_far_future_today(
    db_session: Session,
) -> None:
    """A seed run long after the old fixed October-2026 dates must still
    produce slots on current/future dates rather than stale ones."""
    far_future_today = date(2030, 1, 15)

    seed_demo_data(db_session, today=far_future_today)

    slot_dates = {
        slot_date
        for slot_date in db_session.scalars(select(ProcurementSlot.slot_date)).all()
    }

    assert slot_dates == set(_demo_dates(far_future_today))
    assert all(slot_date > far_future_today for slot_date in slot_dates)


def test_seed_is_idempotent_for_a_fixed_reference_date(db_session: Session) -> None:
    """Re-seeding on the *same* reference date must not create duplicates,
    matching the existing idempotency guarantee for a given day."""
    fixed_today = date(2027, 6, 1)

    first = seed_demo_data(db_session, today=fixed_today)
    second = seed_demo_data(db_session, today=fixed_today)

    assert first == second == EXPECTED_COUNTS
