from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import ThroughputSnapshot
from app.repositories import procurement as procurement_repository
from app.repositories import throughput as throughput_repository

# A single completed service says nothing about pace - we need at least two
# measured gaps between consecutive service starts (i.e. three completions)
# before an average is stable enough to trust as a new throughput snapshot.
MIN_COMPLETED_SERVICES_FOR_SNAPSHOT = 3

# Recalculate from a bounded, recent window of completions rather than a
# centre's full lifetime history, so the metric tracks how the centre is
# performing lately (extra staff added, a booth closed, etc.) instead of
# being dragged down by very old data as more history accumulates.
RECALCULATION_LOOKBACK_LIMIT = 50


@dataclass
class ThroughputError(Exception):
    detail: str
    status_code: int


def _service_start_intervals_minutes(start_times: list[datetime]) -> list[Decimal]:
    """Return the minute-gaps between consecutive service starts, restricted
    to gaps that fall on the same calendar date.

    ``served_at`` marks when a farmer's service began. On a single-queue
    centre, the gap between one farmer's service start and the next farmer's
    service start is exactly the pace at which the centre works through its
    queue, which is the quantity the ETA service needs. Gaps that cross a
    calendar date boundary are dropped: they almost always reflect the
    centre being closed overnight rather than a genuinely slow service, and
    would otherwise swamp the average with multi-hour outliers.
    """
    intervals: list[Decimal] = []
    for previous, current in zip(start_times, start_times[1:]):
        if previous.date() != current.date():
            continue
        gap_minutes = Decimal((current - previous).total_seconds()) / Decimal(60)
        if gap_minutes > 0:
            intervals.append(gap_minutes)
    return intervals


def calculate_average_service_minutes(session: Session, centre_id: int) -> Decimal | None:
    """Calculate the average minutes-per-farmer service pace for a centre
    from its recent completed queue operations.

    Returns ``None`` when there isn't enough history to produce a stable
    average (see ``MIN_COMPLETED_SERVICES_FOR_SNAPSHOT``) rather than
    raising, since "not enough data yet" is an ordinary, expected state for
    a newly onboarded or freshly reset centre - callers should treat that
    the same as "no snapshot available".
    """
    start_times = throughput_repository.list_recent_service_start_times(
        session, centre_id, limit=RECALCULATION_LOOKBACK_LIMIT
    )
    if len(start_times) < MIN_COMPLETED_SERVICES_FOR_SNAPSHOT:
        return None

    intervals = _service_start_intervals_minutes(start_times)
    if not intervals:
        return None

    average = sum(intervals) / Decimal(len(intervals))
    return average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recalculate_throughput(session: Session, centre_id: int) -> ThroughputSnapshot | None:
    """Recalculate and persist a new throughput snapshot for a centre.

    Returns ``None`` (without writing anything) when there isn't yet enough
    completed queue history to produce a trustworthy average. The ETA
    service already falls back to a sane default average when no snapshot
    exists, so silently declining to persist here is the safe behaviour.
    """
    average_minutes = calculate_average_service_minutes(session, centre_id)
    if average_minutes is None:
        return None

    try:
        snapshot = throughput_repository.create_snapshot(session, centre_id, average_minutes)
        session.commit()
        session.refresh(snapshot)
        return snapshot
    except Exception:
        session.rollback()
        raise


def recalculate_throughput_for_centre(
    session: Session,
    centre_id: int,
) -> ThroughputSnapshot:
    """Validate a centre exists, then recalculate its throughput snapshot.

    Intended for the manually-triggered admin endpoint. Unlike
    ``recalculate_throughput`` (used internally right after a queue
    completion, where the centre is already known to be valid), this raises
    a ``ThroughputError`` for both "centre not found" and "insufficient
    data" so a caller hitting the endpoint directly gets an explicit,
    actionable response instead of a silent ``None``.
    """
    centre = procurement_repository.get_centre(session, centre_id)
    if centre is None:
        raise ThroughputError("Procurement centre not found", 404)

    snapshot = recalculate_throughput(session, centre_id)
    if snapshot is None:
        raise ThroughputError(
            "Insufficient completed queue history to calculate throughput "
            "for this centre",
            409,
        )
    return snapshot
