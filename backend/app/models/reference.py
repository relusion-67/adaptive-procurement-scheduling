"""Reference/external agricultural data model.

This is intentionally kept separate from the operational domain models in
``app/models/domain.py`` (``Booking``, ``QueueEntry``, ``ThroughputSnapshot``,
etc.). Those tables hold real application-generated events (a farmer booked
a slot, a queue entry was served). ``ReferenceDataset`` instead holds
external/official statistical context (district agricultural statistics,
market-price observations) that is imported out-of-band and carries its own
provenance.

The scheduling engine (``app/services/scheduling.py``) does not read this
table. Keeping the two concerns in separate tables makes it structurally
impossible for reference/context data to be mistaken for, or silently
blended into, real operational data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

# The only four provenance states this table recognizes. Enforced both at
# the application layer (see app/services/reference_data.py) and at the
# database layer via a CHECK constraint below, so a bad value can't be
# written by a future bug, a direct SQL statement, or another writer.
DATA_STATUS_VALUES = ("REAL", "DERIVED", "SIMULATED", "DEMO")


class ReferenceDataset(Base):
    """A single external/official statistical fact, with provenance.

    One row = one labeled metric value for a district/season/commodity,
    tagged with where it came from. Both "district/season agricultural
    statistics" and "AGMARKNET-style market price observations" fit this
    same shape, so a single table is used rather than one table per
    dataset type.
    """

    __tablename__ = "reference_datasets"
    __table_args__ = (
        CheckConstraint(
            "data_status IN ('REAL', 'DERIVED', 'SIMULATED', 'DEMO')",
            name="ck_reference_datasets_data_status",
        ),
        # A REAL row must always be able to answer "where did this come
        # from" - enforced here, not only in app/services/reference_data.py,
        # so it holds even against a direct SQL statement, a future ORM
        # bug, or a second writer that bypasses the import service.
        CheckConstraint(
            "data_status != 'REAL' OR "
            "(source IS NOT NULL AND source_reference IS NOT NULL "
            "AND retrieved_at IS NOT NULL)",
            name="ck_reference_datasets_real_requires_provenance",
        ),
        # Import identity: the same (dataset_type, district,
        # season_or_period, metric_name, source) must never appear twice.
        # This is the database-level backstop for the import service's
        # duplicate check (app/repositories/reference.find_existing_row) -
        # it is what makes duplicate handling safe against a race between
        # two concurrent import runs, not just against sequential re-runs.
        # NULL `source` values are not considered equal by SQL UNIQUE
        # semantics, so this does not constrain DERIVED/SIMULATED/DEMO
        # rows with no source; it fully constrains REAL rows, since the
        # CHECK constraint above guarantees REAL rows always have a
        # non-null source.
        UniqueConstraint(
            "dataset_type",
            "district",
            "season_or_period",
            "metric_name",
            "source",
            name="uq_reference_datasets_import_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # What kind of dataset this row came from, e.g. "SEASON_CROP_REPORT",
    # "AGMARKNET_PRICE". Free-text rather than an enum: the set of dataset
    # types is expected to grow as new official sources are added, and
    # this table is not read by any code path that needs a closed set.
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)

    district: Mapped[str] = mapped_column(String(255), nullable=False)

    # e.g. "2024-25 Kharif" for a season report, or an ISO date for a
    # daily market-price observation. Free-text for the same reason as
    # dataset_type.
    season_or_period: Mapped[str] = mapped_column(String(50), nullable=False)

    # e.g. "paddy_area_hectares", "modal_price_per_quintal".
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)

    data_status: Mapped[str] = mapped_column(String(20), nullable=False)

    # source/source_reference/retrieved_at are required for REAL rows -
    # enforced by the ck_reference_datasets_real_requires_provenance CHECK
    # constraint above, not just by the import layer. They stay nullable
    # at the schema level so DERIVED/SIMULATED/DEMO rows are not forced to
    # fabricate a source.
    source: Mapped[str | None] = mapped_column(String(255))
    source_reference: Mapped[str | None] = mapped_column(String(500))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # The original imported record, kept verbatim for audit purposes.
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
