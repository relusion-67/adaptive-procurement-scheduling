from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.base import Base
from app.models import (  # noqa: F401
    Booking,
    Farmer,
    NotificationLog,
    ProcurementCentre,
    ProcurementSlot,
    QueueEntry,
    ThroughputSnapshot,
)

EXPECTED_TABLES = {
    "farmers",
    "procurement_centres",
    "procurement_slots",
    "bookings",
    "queue_entries",
    "throughput_snapshots",
    "notification_logs",
}


def test_models_are_importable_and_registered_in_metadata() -> None:
    metadata_tables = set(Base.metadata.tables.keys())
    assert EXPECTED_TABLES.issubset(metadata_tables)


def test_migration_creates_schema_consistent_with_model_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sqlite_db_path = tmp_path / "phase15_data_layer.sqlite3"
    sqlite_url = f"sqlite:///{sqlite_db_path}"
    backend_dir = Path(__file__).resolve().parents[1]

    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(db_tables)

    for table_name in EXPECTED_TABLES:
        model_columns = {
            column.name for column in Base.metadata.tables[table_name].columns.values()
        }
        db_columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert model_columns == db_columns

    command.downgrade(alembic_cfg, "base")
