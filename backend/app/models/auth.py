from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class UserRole(str, enum.Enum):
    """The three roles this application's RBAC model recognizes.

    FARMER: owns their own farmer profile/bookings and nothing else.
    CENTRE_STAFF: scoped to exactly one procurement centre's operations.
    ADMIN: full administrative access, including throughput management.
    """

    FARMER = "FARMER"
    CENTRE_STAFF = "CENTRE_STAFF"
    ADMIN = "ADMIN"


class User(Base):
    """Authentication identity for the API.

    A User is deliberately kept separate from the pre-existing Farmer
    table: Farmer is a procurement-domain record (name/phone/village) that
    predates authentication, while User is the credential + role record
    that authorization decisions are based on. A FARMER-role user is linked
    to exactly one Farmer via `farmer_id`; a CENTRE_STAFF-role user is
    scoped to exactly one ProcurementCentre via `centre_id`. ADMIN users
    need neither.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    farmer_id: Mapped[int | None] = mapped_column(
        ForeignKey("farmers.id"), nullable=True, unique=True
    )
    centre_id: Mapped[int | None] = mapped_column(
        ForeignKey("procurement_centres.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    farmer: Mapped["Farmer | None"] = relationship()  # noqa: F821
    centre: Mapped["ProcurementCentre | None"] = relationship()  # noqa: F821
