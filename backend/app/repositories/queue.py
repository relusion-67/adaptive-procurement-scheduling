from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import QueueEntry, QueueStatus


LIVE_QUEUE_STATUSES = (QueueStatus.WAITING, QueueStatus.CALLED, QueueStatus.SERVING)


def get_queue_entry(session: Session, queue_entry_id: int) -> QueueEntry | None:
    return session.get(QueueEntry, queue_entry_id)


def get_queue_entry_for_update(session: Session, queue_entry_id: int) -> QueueEntry | None:
    return session.scalar(
        select(QueueEntry)
        .where(QueueEntry.id == queue_entry_id)
        .with_for_update()
    )


def get_queue_entry_for_booking(
    session: Session,
    booking_id: int,
) -> QueueEntry | None:
    return session.scalar(select(QueueEntry).where(QueueEntry.booking_id == booking_id))


def next_token_number(session: Session, centre_id: int) -> int:
    latest_token = session.scalar(
        select(func.max(QueueEntry.token_number)).where(QueueEntry.centre_id == centre_id)
    )
    return (latest_token or 0) + 1


def create_queue_entry(session: Session, queue_entry: QueueEntry) -> QueueEntry:
    session.add(queue_entry)
    session.flush()
    return queue_entry


def list_live_queue(session: Session, centre_id: int) -> list[QueueEntry]:
    operational_priority = case(
        (QueueEntry.queue_status == QueueStatus.SERVING, 0),
        (QueueEntry.queue_status == QueueStatus.CALLED, 1),
        else_=2,
    )
    return list(
        session.scalars(
            select(QueueEntry)
            .where(
                QueueEntry.centre_id == centre_id,
                QueueEntry.queue_status.in_(LIVE_QUEUE_STATUSES),
            )
            .order_by(operational_priority, QueueEntry.token_number, QueueEntry.id)
        )
    )


def get_next_waiting_for_update(session: Session, centre_id: int) -> QueueEntry | None:
    return session.scalar(
        select(QueueEntry)
        .where(
            QueueEntry.centre_id == centre_id,
            QueueEntry.queue_status == QueueStatus.WAITING,
        )
        .order_by(QueueEntry.token_number, QueueEntry.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
