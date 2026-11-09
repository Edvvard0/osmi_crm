"""module 11: audit_settings (system_settings, индексы журнала и сессий, права audit_log)

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("value", pg.JSONB(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "GRANT SELECT, INSERT, UPDATE ON system_settings TO crm_app; END IF; END $$"
    )
    # Журнал — только добавление (повтор из 0002 идемпотентен).
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM crm_app; END IF; END $$"
    )
    op.create_index(
        "ix_audit_log_location", "audit_log", ["location_id", sa.text("created_at DESC")]
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action", sa.text("created_at DESC")])
    op.create_index(
        "ix_refresh_sessions_family",
        "refresh_sessions",
        ["family_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_refresh_sessions_revoked",
        "refresh_sessions",
        ["revoked_at"],
        postgresql_where=sa.text("revoked_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_sessions_revoked", table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_family", table_name="refresh_sessions")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_location", table_name="audit_log")
    op.drop_table("system_settings")
