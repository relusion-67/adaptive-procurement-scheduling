"""add role/resource consistency check constraint on users

Defense-in-depth only: the application layer (app/services/auth.py) is
what actually enforces that FARMER users have a farmer_id and no
centre_id, CENTRE_STAFF users have a centre_id and no farmer_id, and
ADMIN users have neither. This constraint backstops that invariant at the
database layer in case of a future application-level bug, direct SQL, or
another writer to this table - it is not itself the security fix for the
CENTRE_STAFF public self-registration vulnerability.

Revision ID: 20260905_01
Revises: 20260904_01
Create Date: 2026-09-05 00:00:00
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260905_01"
down_revision = "20260904_01"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_users_role_resource_consistency"

# batch_alter_table is used (rather than a bare op.create_check_constraint)
# so this migration works unmodified on both SQLite (which cannot ALTER a
# CHECK constraint onto an existing table directly and needs the
# copy-and-swap that batch mode performs) and PostgreSQL (where batch mode
# transparently falls back to a plain ALTER TABLE).
CHECK_SQL = (
    "(role = 'FARMER' AND farmer_id IS NOT NULL AND centre_id IS NULL) OR "
    "(role = 'CENTRE_STAFF' AND centre_id IS NOT NULL AND farmer_id IS NULL) OR "
    "(role = 'ADMIN' AND farmer_id IS NULL AND centre_id IS NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint(CONSTRAINT_NAME, CHECK_SQL)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
