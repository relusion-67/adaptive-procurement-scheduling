"""Query-only access to ``reference_datasets``.

Mirrors the style of the other repositories in this package (e.g.
``app/repositories/throughput.py``): plain functions over a ``Session``,
no business logic, no HTTP concerns.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import nullslast, select
from sqlalchemy.orm import Session

from app.models import ReferenceDataset


def list_reference_data(
    session: Session,
    *,
    district: str | None = None,
    dataset_type: str | None = None,
    metric_name: str | None = None,
    season_or_period: str | None = None,
) -> list[ReferenceDataset]:
    """Return reference rows matching the given filters (all optional).

    Ordered newest-first by ``retrieved_at`` (falling back to
    ``imported_at``/``id`` for rows without a ``retrieved_at``), which is
    the order a caller almost always wants: "what do we currently know".

    ``nullslast()`` is required here rather than a bare ``.desc()``:
    SQLite and PostgreSQL disagree on where NULLs sort by default on a
    descending column (SQLite: last: PostgreSQL: first), so a bare
    ``retrieved_at.desc()`` would put undated DEMO/SIMULATED rows ahead of
    dated REAL rows in production while appearing correct under the
    SQLite-backed test suite.

    ``season_or_period`` was added for Milestone 2's procurement/scheduling
    integration (app/services/procurement_context.py), which needs to
    support matching on all four fields the requirements call out
    (district, season_or_period, metric_name, dataset_type). It is
    optional and additive - every existing caller that doesn't pass it is
    unaffected.
    """
    query = select(ReferenceDataset)
    if district is not None:
        query = query.where(ReferenceDataset.district == district)
    if dataset_type is not None:
        query = query.where(ReferenceDataset.dataset_type == dataset_type)
    if metric_name is not None:
        query = query.where(ReferenceDataset.metric_name == metric_name)
    if season_or_period is not None:
        query = query.where(ReferenceDataset.season_or_period == season_or_period)
    query = query.order_by(
        nullslast(ReferenceDataset.retrieved_at.desc()),
        ReferenceDataset.imported_at.desc(),
        ReferenceDataset.id.desc(),
    )
    return list(session.scalars(query))


def get_reference_row(session: Session, reference_id: int) -> ReferenceDataset | None:
    return session.get(ReferenceDataset, reference_id)


def get_latest_for_metric(
    session: Session,
    *,
    district: str,
    dataset_type: str,
    metric_name: str,
) -> ReferenceDataset | None:
    """Most recent single row for one district/dataset_type/metric_name."""
    return session.scalar(
        select(ReferenceDataset)
        .where(
            ReferenceDataset.district == district,
            ReferenceDataset.dataset_type == dataset_type,
            ReferenceDataset.metric_name == metric_name,
        )
        .order_by(
            nullslast(ReferenceDataset.retrieved_at.desc()),
            ReferenceDataset.imported_at.desc(),
            ReferenceDataset.id.desc(),
        )
        .limit(1)
    )


def find_existing_row(
    session: Session,
    *,
    dataset_type: str,
    district: str,
    season_or_period: str,
    metric_name: str,
    source: str | None,
) -> ReferenceDataset | None:
    """Look up a row with the same import identity.

    Used by the import CLI to implement duplicate-import prevention: a row
    is considered "the same fact" when it has the same dataset_type,
    district, season_or_period, metric_name, and source. See
    ``app/db/import_reference_data.py`` for how this is applied.
    """
    query = select(ReferenceDataset).where(
        ReferenceDataset.dataset_type == dataset_type,
        ReferenceDataset.district == district,
        ReferenceDataset.season_or_period == season_or_period,
        ReferenceDataset.metric_name == metric_name,
    )
    if source is None:
        query = query.where(ReferenceDataset.source.is_(None))
    else:
        query = query.where(ReferenceDataset.source == source)
    return session.scalar(query.limit(1))


def create_reference_row(
    session: Session,
    *,
    dataset_type: str,
    district: str,
    season_or_period: str,
    metric_name: str,
    metric_value: Decimal,
    unit: str,
    data_status: str,
    source: str | None,
    source_reference: str | None,
    retrieved_at: datetime | None,
    raw_payload: dict[str, Any] | None = None,
) -> ReferenceDataset:
    row = ReferenceDataset(
        dataset_type=dataset_type,
        district=district,
        season_or_period=season_or_period,
        metric_name=metric_name,
        metric_value=metric_value,
        unit=unit,
        data_status=data_status,
        source=source,
        source_reference=source_reference,
        retrieved_at=retrieved_at,
        raw_payload=raw_payload,
    )
    session.add(row)
    session.flush()
    return row
