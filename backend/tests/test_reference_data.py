"""Migration, model, and repository tests for reference_datasets.

Follows the per-file SQLite fixture pattern used throughout this test
suite (see e.g. tests/test_throughput.py) rather than a shared conftest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import ReferenceDataset
from app.repositories import reference as reference_repository


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'reference_data.sqlite3'}"
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


def _make_row(session: Session, **overrides) -> ReferenceDataset:
    defaults = dict(
        dataset_type="SEASON_CROP_REPORT",
        district="Thanjavur",
        season_or_period="2024-25 Kharif",
        metric_name="paddy_area_hectares",
        metric_value=Decimal("12345.67"),
        unit="hectares",
        data_status="REAL",
        source="Test fixture - Season and Crop Report (not a real dataset)",
        source_reference="https://example.test/season-crop-report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return reference_repository.create_reference_row(session, **defaults)


def test_migration_creates_reference_datasets_table_matching_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_url = f"sqlite:///{tmp_path / 'reference_migration.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    assert "reference_datasets" in inspector.get_table_names()

    model_columns = {
        column.name for column in Base.metadata.tables["reference_datasets"].columns.values()
    }
    db_columns = {column["name"] for column in inspector.get_columns("reference_datasets")}
    assert model_columns == db_columns

    engine.dispose()
    command.downgrade(alembic_cfg, "base")


def test_migration_downgrade_removes_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_url = f"sqlite:///{tmp_path / 'reference_downgrade.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    assert "reference_datasets" not in inspector.get_table_names()
    engine.dispose()


def test_existing_operational_tables_are_untouched_by_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference_datasets migration must not alter any existing table."""
    sqlite_url = f"sqlite:///{tmp_path / 'reference_untouched.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    for table_name in (
        "farmers",
        "procurement_centres",
        "procurement_slots",
        "bookings",
        "queue_entries",
        "throughput_snapshots",
        "notification_logs",
        "users",
    ):
        assert table_name in inspector.get_table_names()

    engine.dispose()
    command.downgrade(alembic_cfg, "base")


def test_migration_creates_expected_constraints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The migration must create all three constraints the model
    declares: the data_status enum check, the REAL-provenance check, and
    the import-identity unique constraint."""
    sqlite_url = f"sqlite:///{tmp_path / 'reference_constraints.sqlite3'}"
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)

    check_names = {c["name"] for c in inspector.get_check_constraints("reference_datasets")}
    assert "ck_reference_datasets_data_status" in check_names
    assert "ck_reference_datasets_real_requires_provenance" in check_names

    unique_names = {u["name"] for u in inspector.get_unique_constraints("reference_datasets")}
    assert "uq_reference_datasets_import_identity" in unique_names

    engine.dispose()
    command.downgrade(alembic_cfg, "base")


def test_valid_reference_row_can_be_created(db_session: Session) -> None:
    row = _make_row(db_session)
    db_session.commit()

    fetched = db_session.get(ReferenceDataset, row.id)
    assert fetched is not None
    assert fetched.data_status == "REAL"
    assert fetched.district == "Thanjavur"
    assert fetched.metric_value == Decimal("12345.67")


@pytest.mark.parametrize("data_status", ["REAL", "DERIVED", "SIMULATED", "DEMO"])
def test_all_four_provenance_states_are_accepted(
    db_session: Session, data_status: str
) -> None:
    row = _make_row(db_session, data_status=data_status)
    db_session.commit()
    assert row.data_status == data_status


def test_invalid_data_status_is_rejected_by_database_constraint(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        _make_row(db_session, data_status="TOTALLY_MADE_UP")
    db_session.rollback()


@pytest.mark.parametrize(
    "missing_field", ["source", "source_reference", "retrieved_at"]
)
def test_real_row_missing_any_provenance_field_is_rejected_by_database_constraint(
    db_session: Session, missing_field: str
) -> None:
    """ck_reference_datasets_real_requires_provenance must reject a REAL
    row missing ANY of source/source_reference/retrieved_at - not just
    catch it in the import service (app/services/reference_data.py)."""
    with pytest.raises(IntegrityError):
        _make_row(db_session, data_status="REAL", **{missing_field: None})
    db_session.rollback()


@pytest.mark.parametrize("data_status", ["DERIVED", "SIMULATED", "DEMO"])
def test_non_real_row_may_have_null_provenance_fields(
    db_session: Session, data_status: str
) -> None:
    """Only REAL rows are required to carry provenance - the other three
    statuses are not forced to fabricate a source."""
    row = _make_row(
        db_session,
        data_status=data_status,
        source=None,
        source_reference=None,
        retrieved_at=None,
    )
    db_session.commit()
    assert row.data_status == data_status
    assert row.source is None


def test_duplicate_import_identity_is_rejected_by_database_unique_constraint(
    db_session: Session,
) -> None:
    """uq_reference_datasets_import_identity is the database-level
    backstop behind the import service's duplicate check - it must reject
    a second row with the same (dataset_type, district, season_or_period,
    metric_name, source) even if something bypasses the service layer's
    pre-check (e.g. a race - see test_reference_import.py for that
    scenario end-to-end)."""
    _make_row(db_session, source="Same Source")
    db_session.commit()

    with pytest.raises(IntegrityError):
        _make_row(db_session, source="Same Source")
    db_session.rollback()


def test_unique_constraint_permits_multiple_null_source_rows(db_session: Session) -> None:
    """SQL UNIQUE semantics treat NULLs as distinct, so two DEMO/SIMULATED
    rows sharing the same identity but no source are both allowed at the
    database level - deduplication for those statuses stays an
    application-level concern (see app/services/reference_data.py), which
    is an intentional, documented trade-off, not a gap introduced here."""
    _make_row(db_session, data_status="DEMO", source=None, source_reference=None, retrieved_at=None)
    db_session.commit()

    row = _make_row(
        db_session, data_status="DEMO", source=None, source_reference=None, retrieved_at=None
    )
    db_session.commit()
    assert row.source is None


def test_repository_filters_by_district(db_session: Session) -> None:
    _make_row(db_session, district="Thanjavur", metric_name="paddy_area_hectares")
    _make_row(db_session, district="Thiruvarur", metric_name="paddy_area_hectares")
    db_session.commit()

    results = reference_repository.list_reference_data(db_session, district="Thanjavur")

    assert len(results) == 1
    assert results[0].district == "Thanjavur"


def test_repository_filters_by_dataset_type_and_metric_name(db_session: Session) -> None:
    _make_row(db_session, dataset_type="SEASON_CROP_REPORT", metric_name="paddy_area_hectares")
    _make_row(db_session, dataset_type="AGMARKNET_PRICE", metric_name="modal_price_per_quintal")
    db_session.commit()

    results = reference_repository.list_reference_data(
        db_session, dataset_type="AGMARKNET_PRICE"
    )
    assert len(results) == 1
    assert results[0].metric_name == "modal_price_per_quintal"

    results = reference_repository.list_reference_data(
        db_session, metric_name="paddy_area_hectares"
    )
    assert len(results) == 1
    assert results[0].dataset_type == "SEASON_CROP_REPORT"


def test_repository_returns_empty_list_for_no_match(db_session: Session) -> None:
    _make_row(db_session)
    db_session.commit()

    results = reference_repository.list_reference_data(db_session, district="Nonexistent")

    assert results == []


def test_get_latest_for_metric_orders_by_retrieved_at(db_session: Session) -> None:
    _make_row(
        db_session,
        source="Older report",
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    newer = _make_row(
        db_session,
        source="Newer report",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.commit()

    latest = reference_repository.get_latest_for_metric(
        db_session,
        district="Thanjavur",
        dataset_type="SEASON_CROP_REPORT",
        metric_name="paddy_area_hectares",
    )

    assert latest is not None
    assert latest.id == newer.id
    assert latest.source == "Newer report"


def test_list_reference_data_sorts_undated_rows_after_dated_rows(db_session: Session) -> None:
    """A row with no retrieved_at (e.g. DEMO/SIMULATED) must sort after
    dated rows regardless of backend NULL-ordering defaults - see the
    nullslast() usage in list_reference_data/get_latest_for_metric."""
    undated = _make_row(
        db_session,
        data_status="DEMO",
        source=None,
        source_reference=None,
        retrieved_at=None,
    )
    dated = _make_row(
        db_session,
        data_status="REAL",
        source="Dated report",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.commit()

    results = reference_repository.list_reference_data(
        db_session, district="Thanjavur", metric_name="paddy_area_hectares"
    )

    assert [row.id for row in results] == [dated.id, undated.id]


def test_find_existing_row_matches_on_identity_and_source(db_session: Session) -> None:
    row = _make_row(db_session, source="Same Source")
    db_session.commit()

    found = reference_repository.find_existing_row(
        db_session,
        dataset_type=row.dataset_type,
        district=row.district,
        season_or_period=row.season_or_period,
        metric_name=row.metric_name,
        source="Same Source",
    )
    assert found is not None
    assert found.id == row.id

    not_found = reference_repository.find_existing_row(
        db_session,
        dataset_type=row.dataset_type,
        district=row.district,
        season_or_period=row.season_or_period,
        metric_name=row.metric_name,
        source="A Different Source",
    )
    assert not_found is None
