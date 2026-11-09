"""module 12: hardening — выравнивание прав роли crm_app (новых таблиц нет)

Идемпотентно (повторный запуск ничего не меняет); при отсутствии роли `crm_app` (dev/тест на
одной роли) и несозданных таблиц ничего не делает.
- служебный ключ heartbeat воркера пишется в system_settings: SELECT/INSERT/UPDATE;
- неизменяемые журналы: audit_log, stock_movements, payments, payroll_adjustments — без
  UPDATE/DELETE/TRUNCATE (проверка через has_table_privilege в tests/test_hardening_api.py).

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_APPEND_ONLY = ("audit_log", "stock_movements", "payments", "payroll_adjustments")


def upgrade() -> None:
    revokes = " ".join(
        f"IF to_regclass('public.{t}') IS NOT NULL THEN "
        f"REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM crm_app; END IF;"
        for t in _APPEND_ONLY
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "  # noqa: S608
        "IF to_regclass('public.system_settings') IS NOT NULL THEN "
        "GRANT SELECT, INSERT, UPDATE ON system_settings TO crm_app; END IF; "
        f"{revokes} END IF; END $$"
    )


def downgrade() -> None:
    # Права намеренно не ослабляются обратно: откат схемы не должен открывать доступ к журналам.
    pass
