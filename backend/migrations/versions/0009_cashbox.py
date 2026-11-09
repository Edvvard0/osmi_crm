"""module 9: cashbox — payments, expense_categories, expenses (seed категорий расходов)

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

NOW = sa.text("now()")
METHODS = "method IN ('cash','card','transfer','other')"

CATEGORIES = (
    "Аренда",
    "Коммунальные услуги",
    "Расходные материалы",
    "Инструмент и оборудование",
    "Реклама",
    "Налоги и сборы",
    "Хозяйственные расходы",
    "Прочее",
)


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("payment_type", sa.String(10), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("refund_of_id", sa.Uuid(), sa.ForeignKey("payments.id")),
        sa.Column("comment", sa.String(500)),
        sa.Column("accepted_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_request_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("payment_type IN ('payment','refund')", name="ck_payments_type"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount"),
        sa.CheckConstraint(METHODS, name="ck_payments_method"),
        sa.CheckConstraint(
            "payment_type = 'payment' OR comment IS NOT NULL", name="ck_payments_refund_comment"
        ),
        sa.CheckConstraint(
            "payment_type = 'refund' OR refund_of_id IS NULL", name="ck_payments_refund_of_null"
        ),
        sa.CheckConstraint(
            "payment_type = 'payment' OR refund_of_id IS NOT NULL",
            name="ck_payments_refund_of_set",
        ),
    )
    op.create_index("ix_payments_location_paid_at", "payments", ["location_id", "paid_at"])
    op.create_index("ix_payments_work_order_id", "payments", ["work_order_id"])
    op.create_index("ix_payments_refund_of_id", "payments", ["refund_of_id"])
    op.create_index(
        "uq_payments_accepted_by_request",
        "payments",
        ["accepted_by", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
    )

    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "uq_expense_categories_lower_name",
        "expense_categories",
        [sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("expense_categories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount"),
        sa.CheckConstraint(METHODS, name="ck_expenses_method"),
    )
    op.create_index("ix_expenses_location_date", "expenses", ["location_id", "expense_date"])

    # Seed категорий расходов (идемпотентно: уникальность по lower(name)).
    for name in CATEGORIES:
        op.execute(
            sa.text(
                "INSERT INTO expense_categories (id, name) VALUES (gen_random_uuid(), :n) "
                "ON CONFLICT DO NOTHING"
            ).bindparams(n=name)
        )

    # Платежи и возвраты неизменяемы; расходы и категории — обычные права.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON expense_categories, expenses TO crm_app; "
        "GRANT SELECT, INSERT ON payments TO crm_app; "
        "REVOKE UPDATE, DELETE, TRUNCATE ON payments FROM crm_app; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.drop_table("expenses")
    op.drop_table("expense_categories")
    op.drop_table("payments")
