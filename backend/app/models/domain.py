from __future__ import annotations

import enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class BookingStatus(str, enum.Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_QUEUE = "IN_QUEUE"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class QueueStatus(str, enum.Enum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    SERVING = "SERVING"
    DONE = "DONE"
    NO_SHOW = "NO_SHOW"


class NotificationChannel(str, enum.Enum):
    SMS = "SMS"
    IVR = "IVR"
    IN_APP = "IN_APP"


class Farmer(Base):
    __tablename__ = "farmers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    village: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    bookings: Mapped[list[Booking]] = relationship(back_populates="farmer")


class ProcurementCentre(Base):
    __tablename__ = "procurement_centres"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    district: Mapped[str] = mapped_column(String(255), nullable=False)
    daily_capacity: Mapped[int] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    slots: Mapped[list[ProcurementSlot]] = relationship(back_populates="centre")
    bookings: Mapped[list[Booking]] = relationship(back_populates="centre")
    queue_entries: Mapped[list[QueueEntry]] = relationship(back_populates="centre")
    throughput_snapshots: Mapped[list[ThroughputSnapshot]] = relationship(
        back_populates="centre"
    )


class ProcurementSlot(Base):
    __tablename__ = "procurement_slots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("procurement_centres.id"),
        nullable=False,
    )
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)

    centre: Mapped[ProcurementCentre] = relationship(back_populates="slots")
    bookings: Mapped[list[Booking]] = relationship(back_populates="slot")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"), nullable=False)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("procurement_centres.id"),
        nullable=False,
    )
    slot_id: Mapped[int] = mapped_column(ForeignKey("procurement_slots.id"), nullable=False)
    crop_type: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity_kg: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        nullable=False,
        default=BookingStatus.BOOKED,
        server_default=BookingStatus.BOOKED.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    farmer: Mapped[Farmer] = relationship(back_populates="bookings")
    centre: Mapped[ProcurementCentre] = relationship(back_populates="bookings")
    slot: Mapped[ProcurementSlot] = relationship(back_populates="bookings")
    queue_entry: Mapped[QueueEntry | None] = relationship(back_populates="booking")
    notification_logs: Mapped[list[NotificationLog]] = relationship(
        back_populates="booking"
    )


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint("centre_id", "token_number", name="uq_queue_centre_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("procurement_centres.id"),
        nullable=False,
    )
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id"),
        nullable=False,
        unique=True,
    )
    token_number: Mapped[int] = mapped_column(nullable=False)
    queue_status: Mapped[QueueStatus] = mapped_column(
        Enum(QueueStatus, name="queue_status"),
        nullable=False,
        default=QueueStatus.WAITING,
        server_default=QueueStatus.WAITING.value,
    )
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    centre: Mapped[ProcurementCentre] = relationship(back_populates="queue_entries")
    booking: Mapped[Booking] = relationship(back_populates="queue_entry")


class ThroughputSnapshot(Base):
    __tablename__ = "throughput_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    centre_id: Mapped[int] = mapped_column(
        ForeignKey("procurement_centres.id"),
        nullable=False,
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    avg_minutes_per_farmer: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    centre: Mapped[ProcurementCentre] = relationship(back_populates="throughput_snapshots")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"),
        nullable=False,
    )
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    delivery_state: Mapped[str] = mapped_column(String(50), nullable=False)

    booking: Mapped[Booking] = relationship(back_populates="notification_logs")
