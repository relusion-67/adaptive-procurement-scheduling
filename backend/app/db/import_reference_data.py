"""Offline/manual import of external/official reference data.

This is the *only* path by which a row can be written to
``reference_datasets`` (see ``app/api/routers/reference.py`` - there is no
HTTP write endpoint). It is intentionally a manually-run CLI script, not an
automatic startup task and not something triggered by an API request: the
professor's data-realism question is answered by "a human downloaded an
official file and ran this command," not by an unverified live scrape or a
service pretending to have a real-time feed it doesn't have.

Usage
-----

    python -m app.db.import_reference_data <csv_path> \\
        --data-status REAL \\
        --source "Tamil Nadu Season and Crop Report 2024-25" \\
        --source-reference "https://www.tn.gov.in/<...>.pdf" \\
        --retrieved-at 2026-09-01

CSV format
----------

The CSV must have a header row with exactly these columns (order does not
matter, extra columns are ignored but preserved in ``raw_payload``):

    dataset_type, district, season_or_period, metric_name, metric_value, unit

``data_status``, ``source``, ``source_reference``, and ``retrieved_at`` are
NOT read from the CSV. They are supplied once, explicitly, as CLI
arguments for the whole import run - see the module docstring in
``app/services/reference_data.py`` for why a CSV is never assumed to be
"automatically official" just because it parses.

For a REAL import, ``--source``, ``--source-reference``, and
``--retrieved-at`` are all required; the import refuses to run without
them (see ``validate_import_configuration``).

Exit behavior
-------------

The import is all-or-nothing (see ``import_rows``'s docstring): if any row
in the CSV fails validation, nothing is written and every problem found is
printed so they can all be fixed in one pass. Rows that already exist
(same dataset_type/district/season_or_period/metric_name/source) are
skipped, not re-inserted - re-running the same command twice is safe.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.db.session import SessionLocal
from app.services.reference_data import (
    ReferenceImportConfigError,
    import_rows,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a CSV of external/official reference data into "
        "the reference_datasets table.",
    )
    parser.add_argument("csv_path", type=Path, help="Path to the CSV file to import")
    parser.add_argument(
        "--data-status",
        required=True,
        choices=("REAL", "DERIVED", "SIMULATED", "DEMO"),
        help="Provenance tag applied to every row in this import run",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Human-readable name of the source (e.g. an official report "
        "title or 'data.gov.in AGMARKNET'). Required for --data-status REAL.",
    )
    parser.add_argument(
        "--source-reference",
        default=None,
        help="URL or document identifier for the source. Required for "
        "--data-status REAL.",
    )
    parser.add_argument(
        "--retrieved-at",
        default=None,
        help="ISO date/datetime this data was actually retrieved/downloaded "
        "(e.g. 2026-09-01). Required for --data-status REAL.",
    )
    return parser.parse_args(argv)


def _parse_retrieved_at(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ReferenceImportConfigError(
            f"--retrieved-at {raw!r} is not a valid ISO date/datetime"
        ) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _read_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.csv_path.exists():
        print(f"CSV file not found: {args.csv_path}", file=sys.stderr)
        return 1

    try:
        retrieved_at = _parse_retrieved_at(args.retrieved_at)
    except ReferenceImportConfigError as error:
        print(f"Import configuration error: {error}", file=sys.stderr)
        return 1

    rows = _read_csv_rows(args.csv_path)
    if not rows:
        print(f"No data rows found in {args.csv_path}", file=sys.stderr)
        return 1

    with SessionLocal() as session:
        try:
            result = import_rows(
                session,
                rows,
                data_status=args.data_status,
                source=args.source,
                source_reference=args.source_reference,
                retrieved_at=retrieved_at,
            )
        except ReferenceImportConfigError as error:
            print(f"Import configuration error: {error}", file=sys.stderr)
            return 1

    if result.errors:
        print(f"Import FAILED - {len(result.errors)} invalid row(s), nothing was imported:")
        for row_error in result.errors:
            print(f"  row {row_error.row_number}: {row_error.reason}")
        return 1

    print(
        f"Import complete: {len(result.inserted)} row(s) inserted, "
        f"{len(result.skipped_duplicates)} row(s) skipped as already imported."
    )
    if result.skipped_duplicates:
        skipped_text = ", ".join(str(n) for n in result.skipped_duplicates)
        print(f"  skipped rows (already present): {skipped_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
