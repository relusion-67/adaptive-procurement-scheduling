"""Tests for the reference-data import validation/service layer
(app/services/reference_data.py) and the CLI wrapper
(app/db/import_reference_data.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import import_reference_data as import_cli
from app.models import ReferenceDataset
from app.services import reference_data as reference_service


@pytest.fixture
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    sqlite_url = f"sqlite:///{tmp_path / 'reference_import.sqlite3'}"
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


VALID_ROW = {
    "dataset_type": "SEASON_CROP_REPORT",
    "district": "Thanjavur",
    "season_or_period": "2024-25 Kharif",
    "metric_name": "paddy_area_hectares",
    "metric_value": "12345.67",
    "unit": "hectares",
}


# ---------------------------------------------------------------------------
# validate_import_configuration
# ---------------------------------------------------------------------------


def test_real_import_requires_source_source_reference_and_retrieved_at() -> None:
    with pytest.raises(reference_service.ReferenceImportConfigError):
        reference_service.validate_import_configuration(
            data_status="REAL",
            source=None,
            source_reference=None,
            retrieved_at=None,
        )


def test_real_import_succeeds_with_all_provenance_fields() -> None:
    reference_service.validate_import_configuration(
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )  # must not raise


def test_demo_import_does_not_require_provenance_fields() -> None:
    reference_service.validate_import_configuration(
        data_status="DEMO",
        source=None,
        source_reference=None,
        retrieved_at=None,
    )  # must not raise


def test_invalid_data_status_is_rejected_before_any_row_is_touched() -> None:
    with pytest.raises(reference_service.ReferenceImportConfigError):
        reference_service.validate_import_configuration(
            data_status="NOT_A_REAL_STATUS",
            source="x",
            source_reference="y",
            retrieved_at=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# validate_row
# ---------------------------------------------------------------------------


def test_valid_row_passes_validation() -> None:
    cleaned, error = reference_service.validate_row(VALID_ROW, row_number=1)
    assert error is None
    assert cleaned["metric_value"] == Decimal("12345.67")
    assert cleaned["district"] == "Thanjavur"


@pytest.mark.parametrize("missing_column", list(reference_service.REQUIRED_CSV_COLUMNS))
def test_row_missing_required_column_is_rejected(missing_column: str) -> None:
    row = dict(VALID_ROW)
    row[missing_column] = ""

    cleaned, error = reference_service.validate_row(row, row_number=3)

    assert cleaned == {}
    assert error is not None
    assert error.row_number == 3
    assert missing_column in error.reason


def test_row_with_non_numeric_metric_value_is_rejected() -> None:
    row = dict(VALID_ROW, metric_value="not-a-number")

    cleaned, error = reference_service.validate_row(row, row_number=5)

    assert cleaned == {}
    assert error is not None
    assert "metric_value" in error.reason


def test_malformed_metric_value_is_never_coerced_to_zero() -> None:
    """A blank/invalid metric_value must be rejected, never silently
    turned into 0 or any other default."""
    row = dict(VALID_ROW, metric_value="")

    cleaned, error = reference_service.validate_row(row, row_number=2)

    assert cleaned == {}
    assert error is not None


def test_completely_blank_row_is_recognized_as_blank_not_malformed() -> None:
    blank_row = {column: "" for column in reference_service.REQUIRED_CSV_COLUMNS}
    assert reference_service._is_blank_row(blank_row) is True


def test_partially_filled_row_is_not_recognized_as_blank() -> None:
    partial_row = dict(VALID_ROW, unit="")
    assert reference_service._is_blank_row(partial_row) is False


# ---------------------------------------------------------------------------
# import_rows (batch behavior: all-or-nothing, idempotency)
# ---------------------------------------------------------------------------


def test_import_rows_inserts_valid_rows_with_real_status(db_session: Session) -> None:
    result = reference_service.import_rows(
        db_session,
        [VALID_ROW],
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert result.is_successful
    assert len(result.inserted) == 1
    row = db_session.scalar(select(ReferenceDataset))
    assert row is not None
    assert row.data_status == "REAL"
    assert row.source == "Test fixture source"
    assert row.raw_payload == VALID_ROW


def test_import_rows_rejects_entire_batch_when_any_row_is_malformed(
    db_session: Session,
) -> None:
    """All-or-nothing: one bad row means nothing from the batch is
    committed, even if other rows in the same file were valid."""
    good_row = dict(VALID_ROW)
    bad_row = dict(VALID_ROW, metric_value="garbage", metric_name="other_metric")

    result = reference_service.import_rows(
        db_session,
        [good_row, bad_row],
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert not result.is_successful
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 2
    count = db_session.scalar(select(ReferenceDataset).limit(1))
    assert count is None  # nothing was committed


def test_import_rows_is_idempotent_on_rerun_with_same_source(db_session: Session) -> None:
    kwargs = dict(
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    first = reference_service.import_rows(db_session, [VALID_ROW], **kwargs)
    assert len(first.inserted) == 1
    assert len(first.skipped_duplicates) == 0

    second = reference_service.import_rows(db_session, [VALID_ROW], **kwargs)
    assert len(second.inserted) == 0
    assert second.skipped_duplicates == [1]

    all_rows = list(db_session.scalars(select(ReferenceDataset)))
    assert len(all_rows) == 1  # re-running did not create a duplicate


def test_import_rows_does_not_treat_different_source_as_duplicate(
    db_session: Session,
) -> None:
    reference_service.import_rows(
        db_session,
        [VALID_ROW],
        data_status="REAL",
        source="Source A",
        source_reference="https://example.test/a",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    result = reference_service.import_rows(
        db_session,
        [VALID_ROW],
        data_status="REAL",
        source="Source B",
        source_reference="https://example.test/b",
        retrieved_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    assert len(result.inserted) == 1
    all_rows = list(db_session.scalars(select(ReferenceDataset)))
    assert len(all_rows) == 2


def test_import_rows_dedupes_identical_rows_within_the_same_csv(
    db_session: Session,
) -> None:
    """Two identical data rows inside a single CSV (an accidental copy/paste
    duplicate within one file, as opposed to a duplicate re-run of the
    whole import) must not both be inserted - the second is skipped
    against the first row already flushed earlier in the same batch."""
    result = reference_service.import_rows(
        db_session,
        [VALID_ROW, dict(VALID_ROW)],
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert result.is_successful
    assert len(result.inserted) == 1
    assert result.skipped_duplicates == [2]
    all_rows = list(db_session.scalars(select(ReferenceDataset)))
    assert len(all_rows) == 1


def test_import_rows_handles_duplicate_race_via_database_constraint(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates two import runs racing: a conflicting row already exists
    in the database, but the application-level pre-check
    (find_existing_row) misses it - the exact window a real race would
    open between the check and the insert. The database's UNIQUE
    constraint must still catch it, and import_rows must convert that
    into a clean skipped-duplicate result (via the per-row SAVEPOINT)
    rather than raising or corrupting the rest of the batch."""
    kwargs = dict(
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    # A row with this exact import identity already exists, as if another
    # process had just committed it.
    reference_service.import_rows(db_session, [VALID_ROW], **kwargs)
    assert len(list(db_session.scalars(select(ReferenceDataset)))) == 1

    # Force the pre-check to miss the existing row, to simulate the race
    # window (check-then-insert) rather than relying on real concurrency
    # in a single-threaded test.
    from app.repositories import reference as reference_repository_module

    monkeypatch.setattr(
        reference_repository_module, "find_existing_row", lambda *a, **k: None
    )

    other_row = dict(VALID_ROW, metric_name="different_metric")  # a distinct identity
    result = reference_service.import_rows(
        db_session, [VALID_ROW, other_row], **kwargs
    )

    assert result.is_successful
    # The racing duplicate is caught by the database and skipped, not
    # inserted twice and not raised as an unhandled exception.
    assert result.skipped_duplicates == [1]
    # The second, non-conflicting row in the same batch is unaffected by
    # the first row's savepoint rollback.
    assert len(result.inserted) == 1
    all_rows = list(db_session.scalars(select(ReferenceDataset)))
    assert len(all_rows) == 2


def test_import_rows_skips_trailing_blank_row_without_failing_the_batch(
    db_session: Session,
) -> None:
    """A completely blank trailing row (common in spreadsheet-exported
    CSVs) must not sink an otherwise-valid import."""
    blank_row = {column: "" for column in reference_service.REQUIRED_CSV_COLUMNS}

    result = reference_service.import_rows(
        db_session,
        [VALID_ROW, blank_row],
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert result.is_successful
    assert len(result.inserted) == 1
    assert result.errors == []


def test_import_rows_still_fails_batch_on_partially_filled_row(
    db_session: Session,
) -> None:
    """A row with only SOME fields blank is a real data problem, not a
    harmless spacer row, and must still fail the whole batch."""
    partial_row = dict(VALID_ROW, unit="")

    result = reference_service.import_rows(
        db_session,
        [VALID_ROW, partial_row],
        data_status="REAL",
        source="Test fixture source",
        source_reference="https://example.test/report",
        retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert not result.is_successful
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 2
    count = db_session.scalar(select(ReferenceDataset).limit(1))
    assert count is None


def test_import_rows_refuses_real_without_provenance_before_writing_anything(
    db_session: Session,
) -> None:
    with pytest.raises(reference_service.ReferenceImportConfigError):
        reference_service.import_rows(
            db_session,
            [VALID_ROW],
            data_status="REAL",
            source=None,
            source_reference=None,
            retrieved_at=None,
        )
    count = db_session.scalar(select(ReferenceDataset).limit(1))
    assert count is None


# ---------------------------------------------------------------------------
# CLI wrapper (app/db/import_reference_data.py)
# ---------------------------------------------------------------------------


def _write_csv(tmp_path: Path, rows: list[dict[str, str]], filename: str = "data.csv") -> Path:
    import csv

    path = tmp_path / filename
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_cli_imports_valid_csv_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    csv_path = _write_csv(tmp_path, [VALID_ROW])
    monkeypatch.setattr(import_cli, "SessionLocal", lambda: db_session)
    # SessionLocal() is used as a context manager by the CLI's main(); make
    # the monkeypatched session support that without closing the shared
    # fixture session.
    monkeypatch.setattr(db_session, "__enter__", lambda: db_session, raising=False)
    monkeypatch.setattr(db_session, "__exit__", lambda *a: None, raising=False)

    exit_code = import_cli.main(
        [
            str(csv_path),
            "--data-status",
            "REAL",
            "--source",
            "Test fixture source",
            "--source-reference",
            "https://example.test/report",
            "--retrieved-at",
            "2026-09-01",
        ]
    )

    assert exit_code == 0
    row = db_session.scalar(select(ReferenceDataset))
    assert row is not None
    assert row.data_status == "REAL"


def test_cli_rejects_real_import_missing_source_flags(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, [VALID_ROW])

    exit_code = import_cli.main([str(csv_path), "--data-status", "REAL"])

    assert exit_code == 1


def test_cli_reports_missing_csv_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.csv"

    exit_code = import_cli.main(
        [
            str(missing_path),
            "--data-status",
            "DEMO",
        ]
    )

    assert exit_code == 1


def test_cli_rejects_empty_csv(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("dataset_type,district,season_or_period,metric_name,metric_value,unit\n")

    exit_code = import_cli.main([str(empty_path), "--data-status", "DEMO"])

    assert exit_code == 1


def test_cli_fails_whole_import_on_malformed_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    bad_row = dict(VALID_ROW, metric_value="not-a-number")
    csv_path = _write_csv(tmp_path, [VALID_ROW, bad_row])
    monkeypatch.setattr(import_cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "__enter__", lambda: db_session, raising=False)
    monkeypatch.setattr(db_session, "__exit__", lambda *a: None, raising=False)

    exit_code = import_cli.main(
        [
            str(csv_path),
            "--data-status",
            "REAL",
            "--source",
            "Test fixture source",
            "--source-reference",
            "https://example.test/report",
            "--retrieved-at",
            "2026-09-01",
        ]
    )

    assert exit_code == 1
    count = db_session.scalar(select(ReferenceDataset).limit(1))
    assert count is None
