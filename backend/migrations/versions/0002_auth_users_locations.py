"""module 1: locations, users, user_locations, refresh_sessions, audit_log

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column(
            "timezone", sa.String(64), nullable=False, server_default=sa.text("'Europe/Moscow'")
        ),
        sa.Column("work_start", sa.Time(), nullable=False, server_default=sa.text("'09:00'")),
        sa.Column("work_end", sa.Time(), nullable=False, server_default=sa.text("'21:00'")),
        sa.Column("telegram_chat_id", sa.BigInteger()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("name", name="uq_locations_name"),
        sa.UniqueConstraint("code", name="uq_locations_code"),
        sa.CheckConstraint("code ~ '^[A-Z0-9]{2,10}$'", name="ck_locations_code"),
        sa.CheckConstraint("work_end > work_start", name="ck_locations_work_hours"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("login", pg.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "failed_login_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column("telegram_chat_id", sa.BigInteger()),
        sa.Column("telegram_username", sa.String(64)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("login", name="uq_users_login"),
        sa.UniqueConstraint("telegram_chat_id", name="uq_users_telegram_chat_id"),
        sa.CheckConstraint("login ~ '^[a-z0-9._-]{3,50}$'", name="ck_users_login"),
        sa.CheckConstraint("role IN ('mechanic','manager','director')", name="ck_users_role"),
    )
    op.create_table(
        "user_locations",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("ip", pg.INET()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
    )
    op.create_index(
        "ix_refresh_sessions_user_active",
        "refresh_sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_refresh_sessions_family_id", "refresh_sessions", ["family_id"])
    op.create_index("ix_refresh_sessions_expires_at", "refresh_sessions", ["expires_at"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Uuid()),
        sa.Column("location_id", sa.Uuid()),
        sa.Column("changes", pg.JSONB()),
        sa.Column("ip", pg.INET()),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", [sa.text("created_at DESC")])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_user", "audit_log", ["user_id", sa.text("created_at DESC")])
    # Журнал только для добавления: у роли приложения нет UPDATE/DELETE/TRUNCATE.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM crm_app; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("refresh_sessions")
    op.drop_table("user_locations")
    op.drop_table("users")
    op.drop_table("locations")
