"""module 8: inventory (stock_balances, stock_movements, FK work_order_parts.stock_movement_id)

Revision ID: 0008
Revises: 0007

Движения неизменяемы: права crm_app (только SELECT/INSERT) и триггер на UPDATE/DELETE.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

NOW = sa.text("now()")
TYPES = (
    "'receipt','issue_to_order','return_from_order','write_off',"
    "'transfer_out','transfer_in','adjustment'"
)


def upgrade() -> None:
    op.create_table(
        "stock_balances",
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), primary_key=True),
        sa.Column("part_id", sa.Uuid(), sa.ForeignKey("parts.id"), primary_key=True),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_cost", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("min_quantity", sa.Numeric(12, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("quantity >= 0", name="ck_stock_balances_quantity"),
        sa.CheckConstraint("min_quantity >= 0", name="ck_stock_balances_min_quantity"),
        sa.CheckConstraint("avg_cost >= 0", name="ck_stock_balances_avg_cost"),
    )
    op.create_index("ix_stock_balances_part_id", "stock_balances", ["part_id"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("part_id", sa.Uuid(), sa.ForeignKey("parts.id"), nullable=False),
        sa.Column("movement_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 3), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id")),
        sa.Column("related_movement_id", sa.Uuid(), sa.ForeignKey("stock_movements.id")),
        sa.Column("supplier", sa.String(200)),
        sa.Column("document_number", sa.String(50)),
        sa.Column("reason", sa.String(500)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(f"movement_type IN ({TYPES})", name="ck_stock_movements_type"),
        sa.CheckConstraint("quantity <> 0", name="ck_stock_movements_quantity"),
    )
    op.create_index(
        "ix_stock_movements_loc_part_created",
        "stock_movements",
        ["location_id", "part_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_stock_movements_work_order_id", "stock_movements", ["work_order_id"])
    op.create_index("ix_stock_movements_related", "stock_movements", ["related_movement_id"])
    op.create_index(
        "ix_stock_movements_loc_created",
        "stock_movements",
        ["location_id", sa.text("created_at DESC")],
    )
    # Защита от двойного сторно и двойного возврата в заказ.
    op.create_index(
        "uq_stock_movements_single_reversal",
        "stock_movements",
        ["related_movement_id"],
        unique=True,
        postgresql_where=sa.text(
            "movement_type = 'adjustment' AND related_movement_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_stock_movements_single_return",
        "stock_movements",
        ["related_movement_id"],
        unique=True,
        postgresql_where=sa.text("movement_type = 'return_from_order'"),
    )

    op.create_foreign_key(
        "fk_work_order_parts_stock_movement",
        "work_order_parts",
        "stock_movements",
        ["stock_movement_id"],
        ["id"],
    )

    # Неизменяемость поверх прав: UPDATE/DELETE запрещены для любой роли.
    op.execute(
        """
        CREATE FUNCTION stock_movements_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'stock_movements are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_stock_movements_immutable BEFORE UPDATE OR DELETE "
        "ON stock_movements FOR EACH ROW EXECUTE FUNCTION stock_movements_immutable()"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON stock_balances TO crm_app; "
        "GRANT SELECT, INSERT ON stock_movements TO crm_app; "
        "REVOKE UPDATE, DELETE, TRUNCATE ON stock_movements FROM crm_app; END IF; END $$"
    )


def downgrade() -> None:
    op.drop_constraint("fk_work_order_parts_stock_movement", "work_order_parts", type_="foreignkey")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_movements_immutable ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS stock_movements_immutable()")
    op.drop_table("stock_movements")
    op.drop_table("stock_balances")
