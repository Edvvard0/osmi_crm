"""module 5: work_orders (location_counters, work_orders, work_order_items, work_order_parts,
work_order_status_history, work_order_comments; FK appointments.work_order_id)

Revision ID: 0005
Revises: 0004a
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004a"
branch_labels = None
depends_on = None

NOW = sa.text("now()")
ZERO = sa.text("0")


def _grant(tables: str, privileges: str) -> None:
    # SQL собирается только из констант модуля, внешнего ввода нет.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "  # noqa: S608
        f"GRANT {privileges} ON {tables} TO crm_app; END IF; END $$"
    )


def _money(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.Numeric(12, 2), nullable=False, server_default=ZERO)


def upgrade() -> None:
    op.create_table(
        "location_counters",
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), primary_key=True),
        sa.Column("counter_type", sa.String(20), primary_key=True),
        sa.Column("last_value", sa.BigInteger(), nullable=False, server_default=ZERO),
        sa.CheckConstraint("counter_type IN ('work_order')", name="ck_location_counters_type"),
    )

    op.create_table(
        "work_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("number", sa.String(20), nullable=False, unique=True),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'new'")),
        sa.Column("manager_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mileage_in", sa.Integer()),
        sa.Column("complaint", sa.String(2000)),
        sa.Column("intake_notes", sa.String(2000)),
        sa.Column("diagnosis", sa.String(4000)),
        sa.Column("planned_ready_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(500)),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default=ZERO),
        _money("works_total"),
        _money("parts_total"),
        _money("discount_total"),
        _money("total"),
        _money("paid_total"),
        sa.Column(
            "payment_status", sa.String(10), nullable=False, server_default=sa.text("'unpaid'")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "department IN ('service','detailing','mixed')", name="ck_work_orders_dept"
        ),
        sa.CheckConstraint(
            "status IN ('new','diagnostics','awaiting_approval','in_progress',"
            "'awaiting_parts','quality_check','ready','closed','cancelled')",
            name="ck_work_orders_status",
        ),
        sa.CheckConstraint("mileage_in >= 0", name="ck_work_orders_mileage"),
        sa.CheckConstraint(
            "status <> 'cancelled' OR cancel_reason IS NOT NULL", name="ck_work_orders_cancel"
        ),
        sa.CheckConstraint("discount_percent BETWEEN 0 AND 100", name="ck_work_orders_discount"),
        sa.CheckConstraint(
            "payment_status IN ('unpaid','partial','paid','refunded')",
            name="ck_work_orders_payment_status",
        ),
    )
    op.create_index("ix_work_orders_location_status", "work_orders", ["location_id", "status"])
    op.create_index(
        "ix_work_orders_location_created",
        "work_orders",
        ["location_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_work_orders_client_id", "work_orders", ["client_id"])
    op.create_index("ix_work_orders_vehicle_id", "work_orders", ["vehicle_id"])
    op.create_index("ix_work_orders_manager_id", "work_orders", ["manager_id"])
    op.create_index(
        "ix_work_orders_planned_open",
        "work_orders",
        ["planned_ready_at"],
        postgresql_where=sa.text("status NOT IN ('closed','cancelled')"),
    )

    op.create_table(
        "work_order_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("services.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(8, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default=ZERO),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("norm_hours", sa.Numeric(5, 2), nullable=False, server_default=ZERO),
        sa.Column("mechanic_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(15), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("actual_minutes", sa.Integer(), nullable=False, server_default=ZERO),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default=ZERO),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "department IN ('service','detailing')", name="ck_work_order_items_dept"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_work_order_items_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_work_order_items_price"),
        sa.CheckConstraint(
            "discount_percent BETWEEN 0 AND 100", name="ck_work_order_items_discount"
        ),
        sa.CheckConstraint(
            "status IN ('pending','in_progress','paused','done','cancelled')",
            name="ck_work_order_items_status",
        ),
    )
    op.create_index("ix_work_order_items_order", "work_order_items", ["work_order_id"])
    op.create_index(
        "ix_work_order_items_mechanic_status", "work_order_items", ["mechanic_id", "status"]
    )
    op.create_index(
        "ix_work_order_items_mechanic_finished", "work_order_items", ["mechanic_id", "finished_at"]
    )

    op.create_table(
        "work_order_parts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("part_id", sa.Uuid(), sa.ForeignKey("parts.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sku", sa.String(50)),
        sa.Column("unit", sa.String(10)),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2)),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        # FK на stock_movements добавит миграция 0008.
        sa.Column("stock_movement_id", sa.Uuid(), unique=True),
        sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("quantity > 0", name="ck_work_order_parts_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_work_order_parts_price"),
    )
    op.create_index("ix_work_order_parts_order", "work_order_parts", ["work_order_id"])

    op.create_table(
        "work_order_status_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("comment", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_work_order_status_history_order",
        "work_order_status_history",
        ["work_order_id", "created_at"],
    )

    op.create_table(
        "work_order_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("work_order_items.id")),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_work_order_comments_order", "work_order_comments", ["work_order_id", "created_at"]
    )

    op.create_foreign_key(
        "appointments_work_order_id_fkey",
        "appointments",
        "work_orders",
        ["work_order_id"],
        ["id"],
    )

    _grant(
        "location_counters, work_orders, work_order_items, work_order_parts",
        "SELECT, INSERT, UPDATE, DELETE",
    )
    _grant("work_order_status_history, work_order_comments", "SELECT, INSERT")


def downgrade() -> None:
    op.drop_constraint("appointments_work_order_id_fkey", "appointments", type_="foreignkey")
    op.drop_table("work_order_comments")
    op.drop_table("work_order_status_history")
    op.drop_table("work_order_parts")
    op.drop_table("work_order_items")
    op.drop_table("work_orders")
    op.drop_table("location_counters")
