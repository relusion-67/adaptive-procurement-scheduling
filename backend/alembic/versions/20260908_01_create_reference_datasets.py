"""create reference_datasets table for external/official agricultural data

Purely additive: creates one new table and touches nothing else. Holds
external/official statistical context (e.g. district agricultural
statistics, AGMARKNET-style market price observations) with explicit
provenance, kept separate from the operational tables (bookings,
queue_entries, throughput_snapshots, ...) that the scheduling engine
reads. See app/models/reference.py for the full rationale.

Three constraints are enforced at the database level, not just in the
application/import layer:
  - data_status is restricted to REAL/DERIVED/SIMULATED/DEMO.
  - a REAL row must always have source, source_reference, and
    retrieved_at populated.
  - (dataset_type, district, season_or_period, metric_name, source) is
    unique, so the import identity used for duplicate detection is
    enforced even under a race between two concurrent import runs.

Revision ID: 20260908_01
Revises: 20260905_01
Create Date: 2026-09-08 00:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260908_01"
down_revision = "20260905_01"
branch_labels = None
depends_on = None

DATA_STATUS_CHECK_NAME = "ck_reference_datasets_data_status"
DATA_STATUS_CHECK_SQL = "data_status IN ('REAL', 'DERIVED', 'SIMULATED', 'DEMO')"

REAL_PROVENANCE_CHECK_NAME = "ck_reference_datasets_real_requires_provenance"
REAL_PROVENANCE_CHECK_SQL = (
    "data_status != 'REAL' OR "
    "(source IS NOT NULL AND source_reference IS NOT NULL AND retrieved_at IS NOT NULL)"
)

IMPORT_IDENTITY_UNIQUE_NAME = "uq_reference_datasets_import_identity"
IMPORT_IDENTITY_COLUMNS = (
    "dataset_type",
    "district",
    "season_or_period",
    "metric_name",
    "source",
)


def upgrade() -> None:
    op.create_table(
        "reference_datasets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_type", sa.String(length=50), nullable=False),
        sa.Column("district", sa.String(length=255), nullable=False),
        sa.Column("season_or_period", sa.String(length=50), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("metric_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("data_status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(DATA_STATUS_CHECK_SQL, name=DATA_STATUS_CHECK_NAME),
        sa.CheckConstraint(REAL_PROVENANCE_CHECK_SQL, name=REAL_PROVENANCE_CHECK_NAME),
        sa.UniqueConstraint(*IMPORT_IDENTITY_COLUMNS, name=IMPORT_IDENTITY_UNIQUE_NAME),
    )
    op.create_index(
        "ix_reference_datasets_lookup",
        "reference_datasets",
        ["district", "dataset_type", "metric_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_reference_datasets_lookup", table_name="reference_datasets")
    op.drop_table("reference_datasets")
