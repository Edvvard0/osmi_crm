"""module 10: reports_payroll — payroll_schemes, payroll_adjustments, индексы отчётов

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "payroll_schemes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scheme_type", sa.String(20), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2)),
        sa.Column("norm_hour_rate", sa.Numeric(12, 2)),
        sa.Column("fixed_monthly", sa.Numeric(12, 2)),
        sa.Column("department", sa.String(10)),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "scheme_type IN ('percent_of_works','per_norm_hour','fixed_plus_percent','fixed')",
            name="ck_payroll_schemes_type",
        ),
        sa.CheckConstraint(
            "percent IS NULL OR percent BETWEEN 0 AND 100", name="ck_payroll_schemes_percent"
        ),
        sa.CheckConstraint(
            "norm_hour_rate IS NULL OR norm_hour_rate >= 0", name="ck_payroll_schemes_rate"
        ),
        sa.CheckConstraint(
            "fixed_monthly IS NULL OR fixed_monthly >= 0", name="ck_payroll_schemes_fixed"
        ),
        sa.CheckConstraint(
            "department IS NULL OR department IN ('service','detailing')",
            name="ck_payroll_schemes_department",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="ck_payroll_schemes_period"
        ),
        sa.CheckConstraint(
            "(scheme_type = 'percent_of_works' AND percent IS NOT NULL "
            "AND norm_hour_rate IS NULL AND fixed_monthly IS NULL) "
            "OR (scheme_type = 'per_norm_hour' AND norm_hour_rate IS NOT NULL "
            "AND percent IS NULL AND fixed_monthly IS NULL) "
            "OR (scheme_type = 'fixed_plus_percent' AND percent IS NOT NULL "
            "AND fixed_monthly IS NOT NULL AND norm_hour_rate IS NULL AND department IS NULL) "
            "OR (scheme_type = 'fixed' AND fixed_monthly IS NOT NULL "
            "AND percent IS NULL AND norm_hour_rate IS NULL AND department IS NULL)",
            name="ck_payroll_schemes_fields",
        ),
    )
    op.execute(
        "ALTER TABLE payroll_schemes ADD CONSTRAINT payroll_schemes_no_overlap "
        "EXCLUDE USING gist (user_id WITH =, (coalesce(department, '*')) WITH =, "
        "daterange(valid_from, valid_to, '[]') WITH &&)"
    )
    op.create_index("ix_payroll_schemes_user_from", "payroll_schemes", ["user_id", "valid_from"])

    op.create_table(
        "payroll_adjustments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("amount <> 0", name="ck_payroll_adjustments_amount"),
        sa.CheckConstraint(
            "extract(day FROM period_month) = 1", name="ck_payroll_adjustments_month"
        ),
    )
    op.create_index(
        "ix_payroll_adjustments_user_month", "payroll_adjustments", ["user_id", "period_month"]
    )
    op.create_index("ix_payroll_adjustments_month", "payroll_adjustments", ["period_month"])

    # Индексы отчётов.
    op.create_index(
        "ix_work_orders_closed_location",
        "work_orders",
        ["location_id", "closed_at"],
        postgresql_where=sa.text("status = 'closed'"),
    )
    op.create_index(
        "ix_work_order_items_mechanic_done",
        "work_order_items",
        ["mechanic_id", "finished_at"],
        postgresql_where=sa.text("status = 'done'"),
    )

    # Схемы — обычные права; корректировки неизменяемы (только SELECT, INSERT).
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_schemes TO crm_app; "
        "GRANT SELECT, INSERT ON payroll_adjustments TO crm_app; "
        "REVOKE UPDATE, DELETE, TRUNCATE ON payroll_adjustments FROM crm_app; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.drop_index("ix_work_order_items_mechanic_done", table_name="work_order_items")
    op.drop_index("ix_work_orders_closed_location", table_name="work_orders")
    op.drop_table("payroll_adjustments")
    op.drop_table("payroll_schemes")
