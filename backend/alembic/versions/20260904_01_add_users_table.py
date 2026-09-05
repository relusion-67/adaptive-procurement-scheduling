"""add users table for authentication/rbac

Revision ID: 20260904_01
Revises: 20260902_01
Create Date: 2026-09-04 00:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260904_01"
down_revision = "20260902_01"
branch_labels = None
depends_on = None


user_role_enum = sa.Enum(
    "FARMER",
    "CENTRE_STAFF",
    "ADMIN",
    name="user_role",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("farmer_id", sa.Integer(), nullable=True),
        sa.Column("centre_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["farmer_id"], ["farmers.id"]),
        sa.ForeignKeyConstraint(["centre_id"], ["procurement_centres.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("farmer_id", name="uq_users_farmer_id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    user_role_enum.drop(op.get_bind(), checkfirst=True)
