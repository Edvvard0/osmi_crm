"""module 7: telegram_outbox (telegram_link_codes, notification_settings, notification_outbox)

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

NOW = sa.text("now()")
TABLES = ("telegram_link_codes", "notification_settings", "notification_outbox")


def upgrade() -> None:
    op.create_table(
        "telegram_link_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.CHAR(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("code_hash", name="telegram_link_codes_code_hash_key"),
    )
    op.create_index(
        "ix_telegram_link_codes_user_created",
        "telegram_link_codes",
        ["user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "notification_settings",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("event_type", sa.String(50), primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("text", sa.String(4096), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("last_error", sa.String(500)),
        sa.Column("dedup_key", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','skipped')", name="ck_notification_outbox_status"
        ),
    )
    op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_notification_outbox_chat_status", "notification_outbox", ["chat_id", "status"]
    )
    op.create_index(
        "notification_outbox_dedup",
        "notification_outbox",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )

    for table in TABLES:
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO crm_app; END IF; END $$"
        )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "GRANT USAGE ON SEQUENCE notification_outbox_id_seq TO crm_app; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table("notification_outbox")
    op.drop_table("notification_settings")
    op.drop_table("telegram_link_codes")
