from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QueueEntry, QueueStatus, ThroughputSnapshot


def get_latest_snapshot(session: Session, centre_id: int) -> ThroughputSnapshot | None:
    """Return the most recent throughput snapshot for a centre, if any."""
    return session.scalar(
        select(ThroughputSnapshot)
        .where(ThroughputSnapshot.centre_id == centre_id)
        .order_by(ThroughputSnapshot.snapshot_at.desc(), ThroughputSnapshot.id.desc())
        .limit(1)
    )


def list_recent_service_start_times(
    session: Session,
    centre_id: int,
    limit: int,
) -> list[datetime]:
    """Return the ``served_at`` timestamps of the most recent completed
    queue entries for a centre, oldest-first.

    "Completed" means the entry reached ``QueueStatus.DONE`` after actually
    being served (i.e. ``served_at`` is set). This is the raw signal the
    throughput engine turns into a service-pace average; the query itself
    only fetches and bounds the sample, all interpretation happens in the
    service layer.
    """
    rows = session.scalars(
        select(QueueEntry.served_at)
        .where(
            QueueEntry.centre_id == centre_id,
            QueueEntry.queue_status == QueueStatus.DONE,
            QueueEntry.served_at.is_not(None),
        )
        .order_by(QueueEntry.served_at.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def create_snapshot(
    session: Session,
    centre_id: int,
    avg_minutes_per_farmer: Decimal,
) -> ThroughputSnapshot:
    """Persist a new throughput snapshot using the existing data model.

    Uses the model's ``server_default`` for ``snapshot_at`` (matching how
    every other timestamped row in this codebase is created) rather than
    stamping "now" in Python.
    """
    snapshot = ThroughputSnapshot(
        centre_id=centre_id,
        avg_minutes_per_farmer=avg_minutes_per_farmer,
    )
    session.add(snapshot)
    session.flush()
    return snapshot
