from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import QueueStatus
from app.repositories import queue as queue_repository
from app.repositories import throughput as throughput_repository
from app.services.queue import QueueError

# Fallback average service time (minutes) used when a procurement centre has no
# throughput history yet. This keeps ETA calculation available from day one for
# a newly onboarded centre instead of failing the request. Chosen as a
# conservative, explicit placeholder rather than a magic number inlined at the
# call site; revisit if a product-defined default emerges.
DEFAULT_AVERAGE_SERVICE_MINUTES = Decimal("15.00")

# Queue entries in these states have already left the live queue, so an ETA no
# longer has a meaningful interpretation for them.
TERMINAL_QUEUE_STATUSES = (QueueStatus.DONE, QueueStatus.NO_SHOW)


@dataclass
class QueueETA:
    queue_entry_id: int
    token_number: int
    queue_position: int
    farmers_ahead: int
    average_service_minutes: Decimal
    estimated_wait_minutes: Decimal
    queue_status: QueueStatus
    calculated_at: datetime


def calculate_eta(session: Session, queue_entry_id: int) -> QueueETA:
    queue_entry = queue_repository.get_queue_entry(session, queue_entry_id)
    if queue_entry is None:
        raise QueueError("Queue entry not found", 404)
    if queue_entry.queue_status in TERMINAL_QUEUE_STATUSES:
        raise QueueError(
            "Cannot calculate ETA for a queue entry with status "
            f"{queue_entry.queue_status.value}",
            409,
        )

    live_queue = queue_repository.list_live_queue(session, queue_entry.centre_id)
    try:
        position_index = next(
            index for index, entry in enumerate(live_queue) if entry.id == queue_entry.id
        )
    except StopIteration:
        # Defensive: the entry has a live status but wasn't returned by the
        # shared queue ordering. Treat consistently with "not found" rather
        # than exposing an internal inconsistency to the caller.
        raise QueueError("Queue entry not found", 404)

    farmers_ahead = position_index
    queue_position = position_index + 1

    snapshot = throughput_repository.get_latest_snapshot(session, queue_entry.centre_id)
    average_service_minutes = (
        Decimal(snapshot.avg_minutes_per_farmer)
        if snapshot is not None
        else DEFAULT_AVERAGE_SERVICE_MINUTES
    )

    estimated_wait_minutes = Decimal(farmers_ahead) * average_service_minutes

    return QueueETA(
        queue_entry_id=queue_entry.id,
        token_number=queue_entry.token_number,
        queue_position=queue_position,
        farmers_ahead=farmers_ahead,
        average_service_minutes=average_service_minutes,
        estimated_wait_minutes=estimated_wait_minutes,
        queue_status=queue_entry.queue_status,
        calculated_at=datetime.now(timezone.utc),
    )
