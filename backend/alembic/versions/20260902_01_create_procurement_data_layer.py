"""create procurement data layer

Revision ID: 20260902_01
Revises:
Create Date: 2026-09-02 05:45:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260902_01"
down_revision = None
branch_labels = None
depends_on = None


booking_status_enum = sa.Enum(
    "BOOKED",
    "CHECKED_IN",
    "IN_QUEUE",
    "PROCESSING",
    "COMPLETED",
    "MISSED",
    "CANCELLED",
    name="booking_status",
)

queue_status_enum = sa.Enum(
    "WAITING",
    "CALLED",
    "SERVING",
    "DONE",
    "NO_SHOW",
    name="queue_status",
)

notification_channel_enum = sa.Enum(
    "SMS",
    "IVR",
    "IN_APP",
    name="notification_channel",
)


def upgrade() -> None:
    op.create_table(
        "farmers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("village", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "procurement_centres",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("district", sa.String(length=255), nullable=False),
        sa.Column("daily_capacity", sa.Integer(), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "procurement_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["centre_id"], ["procurement_centres.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("farmer_id", sa.Integer(), nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("crop_type", sa.String(length=100), nullable=False),
        sa.Column("quantity_kg", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "status",
            booking_status_enum,
            server_default=sa.text("'BOOKED'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["centre_id"], ["procurement_centres.id"]),
        sa.ForeignKeyConstraint(["farmer_id"], ["farmers.id"]),
        sa.ForeignKeyConstraint(["slot_id"], ["procurement_slots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "throughput_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "avg_minutes_per_farmer",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["centre_id"], ["procurement_centres.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "queue_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("centre_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("token_number", sa.Integer(), nullable=False),
        sa.Column(
            "queue_status",
            queue_status_enum,
            server_default=sa.text("'WAITING'"),
            nullable=False,
        ),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("served_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.ForeignKeyConstraint(["centre_id"], ["procurement_centres.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id"),
        sa.UniqueConstraint("centre_id", "token_number", name="uq_queue_centre_token"),
    )

    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("channel", notification_channel_enum, nullable=False),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("delivery_state", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("notification_logs")
    op.drop_table("queue_entries")
    op.drop_table("throughput_snapshots")
    op.drop_table("bookings")
    op.drop_table("procurement_slots")
    op.drop_table("procurement_centres")
    op.drop_table("farmers")

    notification_channel_enum.drop(op.get_bind(), checkfirst=True)
    queue_status_enum.drop(op.get_bind(), checkfirst=True)
    booking_status_enum.drop(op.get_bind(), checkfirst=True)
