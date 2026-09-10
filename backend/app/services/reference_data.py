"""Validation and import logic for external/official reference data.

This is the only path by which rows can be tagged ``data_status="REAL"``.
There is deliberately no HTTP write endpoint for this table (see
``app/api/routers/reference.py``); real data enters only through
``app/db/import_reference_data.py`` calling into this module, and this
module is what actually enforces the provenance policy - not just the
CLI's argument parsing.

Kept independent from ``app/services/scheduling.py`` on purpose: this
module never reads from or writes to any operational table (bookings,
queue entries, throughput snapshots, procurement centres/slots). Milestone
2's ``find_reference_context`` (below) is a read-only lookup added to this
same "reference service" boundary - see
``app/services/procurement_context.py`` for the one place that bridges
this module with the operational/procurement domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DATA_STATUS_VALUES, ReferenceDataset
from app.repositories import reference as reference_repository

REQUIRED_CSV_COLUMNS = (
    "dataset_type",
    "district",
    "season_or_period",
    "metric_name",
    "metric_value",
    "unit",
)


@dataclass
class RowValidationError:
    row_number: int  # 1-based, matching a human looking at the CSV in a spreadsheet
    reason: str


@dataclass
class ImportBatchResult:
    """Outcome of one import run. Nothing is committed unless ``errors`` is
    empty - see ``import_rows``' docstring for why the import is
    all-or-nothing.
    """

    inserted: list[ReferenceDataset] = field(default_factory=list)
    skipped_duplicates: list[int] = field(default_factory=list)  # row numbers
    errors: list[RowValidationError] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        return not self.errors


class ReferenceImportConfigError(Exception):
    """Raised for problems with the import *configuration* itself (e.g. a
    REAL import missing required provenance fields), as distinct from a
    problem with an individual CSV row.
    """


def _validate_data_status(data_status: str) -> str | None:
    if data_status not in DATA_STATUS_VALUES:
        allowed = ", ".join(DATA_STATUS_VALUES)
        return f"data_status must be one of ({allowed}), got {data_status!r}"
    return None


def validate_import_configuration(
    *,
    data_status: str,
    source: str | None,
    source_reference: str | None,
    retrieved_at: datetime | None,
) -> None:
    """Validate the batch-level provenance configuration for an import run.

    Raises ``ReferenceImportConfigError`` rather than returning a value:
    a bad configuration means the entire import run should never start,
    which is a different failure mode from a single malformed CSV row.
    """
    status_error = _validate_data_status(data_status)
    if status_error is not None:
        raise ReferenceImportConfigError(status_error)

    if data_status == "REAL":
        missing = [
            name
            for name, value in (
                ("--source", source),
                ("--source-reference", source_reference),
                ("--retrieved-at", retrieved_at),
            )
            if not value
        ]
        if missing:
            raise ReferenceImportConfigError(
                "REAL data requires source, source_reference, and "
                "retrieved_at to be supplied explicitly; missing: "
                + ", ".join(missing)
                + ". This is a deliberate guard: it must never be possible "
                "to import a row tagged REAL without recording where it "
                "actually came from."
            )


def _is_blank_row(row: dict[str, str]) -> bool:
    """True when every required column in ``row`` is missing or blank.

    Distinguishes a harmless empty spacer row from a genuinely malformed
    one: a row with *some* fields filled and others missing still fails
    validation as malformed (see ``validate_row``) rather than being
    silently skipped here.
    """
    return all(
        column not in row or row[column] is None or str(row[column]).strip() == ""
        for column in REQUIRED_CSV_COLUMNS
    )


def validate_row(row: dict[str, str], row_number: int) -> tuple[dict, RowValidationError | None]:
    """Validate a single parsed CSV row (values already read as strings).

    Returns ``(cleaned_fields, None)`` on success, or
    ``({}, RowValidationError)`` on failure. Never coerces an invalid value
    into a default (e.g. a blank/non-numeric metric_value never becomes
    ``0``) - a row that can't be validated is rejected, not guessed at.
    """
    missing_columns = [
        column
        for column in REQUIRED_CSV_COLUMNS
        if column not in row or row[column] is None or str(row[column]).strip() == ""
    ]
    if missing_columns:
        return {}, RowValidationError(
            row_number, f"missing/blank required column(s): {', '.join(missing_columns)}"
        )

    dataset_type = row["dataset_type"].strip()
    district = row["district"].strip()
    season_or_period = row["season_or_period"].strip()
    metric_name = row["metric_name"].strip()
    unit = row["unit"].strip()

    raw_value = row["metric_value"].strip()
    try:
        metric_value = Decimal(raw_value)
    except InvalidOperation:
        return {}, RowValidationError(
            row_number, f"metric_value {raw_value!r} is not a valid decimal number"
        )

    return (
        {
            "dataset_type": dataset_type,
            "district": district,
            "season_or_period": season_or_period,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "unit": unit,
        },
        None,
    )


def import_rows(
    session: Session,
    rows: list[dict[str, str]],
    *,
    data_status: str,
    source: str | None,
    source_reference: str | None,
    retrieved_at: datetime | None,
) -> ImportBatchResult:
    """Validate and import a batch of already-parsed CSV rows.

    All-or-nothing: if any row fails validation, nothing from this batch
    is committed - ``result.errors`` is returned non-empty and the caller
    (the CLI) reports every problem found so they can all be fixed at
    once, rather than the operator discovering them one broken row at a
    time across repeated re-runs. This is the "simpler robust approach"
    chosen over a partial-import mode: it keeps "did this file fully
    import or not" a single yes/no question with no partially-imported
    file to reason about. A completely blank row (every required field
    empty) is treated as an incidental spacer row and skipped rather than
    as a validation failure - see ``_is_blank_row`` - since real
    spreadsheet-exported CSVs commonly contain a trailing blank line and
    that should not sink an otherwise-valid import.

    Idempotency: a row is considered a duplicate of an existing row - and
    is skipped, not re-inserted or updated - when it matches an existing
    row's (dataset_type, district, season_or_period, metric_name, source)
    together. Re-running the same import (same file, same --source) is
    therefore safe and will not create duplicate rows; it will report the
    matching rows as skipped. Importing corrected figures for the same
    fact requires either a different --source/--source-reference (a new
    provenance trail) or a manual correction - this module does not
    silently overwrite a previously-imported REAL value.

    This identity is also enforced by a UNIQUE constraint at the database
    level (``uq_reference_datasets_import_identity``), so the duplicate
    check above is not the only thing preventing a duplicate: if two
    import runs race (both check "not found" before either has
    committed), the database itself rejects the second insert. That
    insert is attempted inside a per-row SAVEPOINT (``session.begin_nested``)
    so a race-losing row is cleanly reported as a skipped duplicate -
    exactly like a duplicate caught by the pre-check - rather than
    aborting the rest of the batch or crashing the import.
    """
    validate_import_configuration(
        data_status=data_status,
        source=source,
        source_reference=source_reference,
        retrieved_at=retrieved_at,
    )

    result = ImportBatchResult()
    cleaned_rows: list[tuple[int, dict]] = []

    for row_number, row in enumerate(rows, start=1):
        if _is_blank_row(row):
            # A row where every required field is empty is a harmless
            # spacer/trailing row - common in spreadsheet-exported CSVs,
            # including real official government exports - not a
            # malformed data row. Skipping it here (rather than failing
            # the whole import) keeps the all-or-nothing safeguard aimed
            # at genuinely bad data, not incidental formatting noise. A
            # row with *some* but not all fields filled is still treated
            # as malformed below, since that reflects an actual data
            # problem rather than an empty line.
            continue
        cleaned, error = validate_row(row, row_number)
        if error is not None:
            result.errors.append(error)
            continue
        cleaned_rows.append((row_number, cleaned))

    if result.errors:
        # All-or-nothing: report every error, insert nothing.
        return result

    for row_number, cleaned in cleaned_rows:
        existing = reference_repository.find_existing_row(
            session,
            dataset_type=cleaned["dataset_type"],
            district=cleaned["district"],
            season_or_period=cleaned["season_or_period"],
            metric_name=cleaned["metric_name"],
            source=source,
        )
        if existing is not None:
            result.skipped_duplicates.append(row_number)
            continue

        try:
            with session.begin_nested():
                row = reference_repository.create_reference_row(
                    session,
                    dataset_type=cleaned["dataset_type"],
                    district=cleaned["district"],
                    season_or_period=cleaned["season_or_period"],
                    metric_name=cleaned["metric_name"],
                    metric_value=cleaned["metric_value"],
                    unit=cleaned["unit"],
                    data_status=data_status,
                    source=source,
                    source_reference=source_reference,
                    retrieved_at=retrieved_at,
                    raw_payload=dict(rows[row_number - 1]),
                )
        except IntegrityError:
            # Lost a race against a concurrent import that inserted the
            # same (dataset_type, district, season_or_period,
            # metric_name, source) identity between our pre-check above
            # and this insert. The SAVEPOINT ensures only this row's
            # attempted insert is rolled back - the rest of the batch, and
            # any rows already inserted earlier in this same call, are
            # unaffected.
            result.skipped_duplicates.append(row_number)
            continue

        result.inserted.append(row)

    session.commit()
    return result


# --------------------------------------------------------------------------
# Read-only lookup for procurement/scheduling integration (Milestone 2)
# --------------------------------------------------------------------------
#
# Everything above this point is about getting REAL data safely INTO
# reference_datasets. Everything below is the read side used by
# app/services/procurement_context.py to bring already-imported reference
# data OUT to the operational domain, as a plain dataclass rather than a
# SQLAlchemy ORM object - so a caller in the procurement/scheduling layer
# never needs to import ``ReferenceDataset`` or touch the ORM directly.


@dataclass(frozen=True)
class ReferenceContext:
    """A read-only, fully explainable projection of one reference row.

    Deliberately mirrors every field called out in the Milestone 2
    explainability requirement - dataset_type, district, season_or_period,
    metric_name, metric_value, unit, data_status, source,
    source_reference, retrieved_at - and nothing else: no database id, no
    imported_at, no raw_payload. Those are DB/import internals a
    procurement/scheduling consumer has no use for.
    """

    dataset_type: str
    district: str
    season_or_period: str
    metric_name: str
    metric_value: Decimal
    unit: str
    data_status: str
    source: str | None
    source_reference: str | None
    retrieved_at: datetime | None


def _to_context(row: ReferenceDataset) -> ReferenceContext:
    return ReferenceContext(
        dataset_type=row.dataset_type,
        district=row.district,
        season_or_period=row.season_or_period,
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        unit=row.unit,
        data_status=row.data_status,
        source=row.source,
        source_reference=row.source_reference,
        retrieved_at=row.retrieved_at,
    )


def find_reference_context(
    session: Session,
    *,
    district: str,
    dataset_type: str | None = None,
    metric_name: str | None = None,
    season_or_period: str | None = None,
) -> list[ReferenceContext]:
    """Deterministic lookup of reference facts for a district.

    Supports matching on all four fields required by Milestone 2
    (district, dataset_type, metric_name, season_or_period); only
    ``district`` is required, since the operational domain (a procurement
    centre) always has a district but has no season/dataset_type/metric
    concept of its own to filter by unless the caller supplies one
    explicitly.

    Returns an empty list - never ``None``, never raises - when nothing
    matches. An empty list IS the correct, expected representation of "no
    reference data for this district/filter combination yet"; callers
    must not treat it as an error.
    """
    rows = reference_repository.list_reference_data(
        session,
        district=district,
        dataset_type=dataset_type,
        metric_name=metric_name,
        season_or_period=season_or_period,
    )
    return [_to_context(row) for row in rows]
