"""extensions: pg_trgm, btree_gist, citext

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for ext in ("pg_trgm", "btree_gist", "citext"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")


def downgrade() -> None:
    for ext in ("citext", "btree_gist", "pg_trgm"):
        op.execute(f"DROP EXTENSION IF EXISTS {ext}")
