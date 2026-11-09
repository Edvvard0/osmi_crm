"""module 12: hardening (заглушка — модуль заменит тело upgrade/downgrade)

Revision ID: 0012
Revises: 0011
"""

from alembic import op  # noqa: F401

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
