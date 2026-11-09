"""module 6: mechanic_workplace (work_logs, part_requests, vehicle_recommendations)

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _grant(tables: str, privileges: str) -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN "
        f"GRANT {privileges} ON {tables} TO crm_app; END IF; END $$"
    )


def upgrade() -> None:
    op.create_table(
        "work_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("work_order_items.id"), nullable=False),
        sa.Column("mechanic_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at", name="ck_work_logs_period"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX work_logs_one_active_per_mechanic "
        "ON work_logs (mechanic_id) WHERE ended_at IS NULL"
    )
    op.create_index("ix_work_logs_mechanic_started", "work_logs", ["mechanic_id", "started_at"])
    op.create_index("ix_work_logs_item_id", "work_logs", ["item_id"])

    op.create_table(
        "part_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("work_order_items.id")),
        sa.Column("mechanic_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("part_id", sa.Uuid(), sa.ForeignKey("parts.id")),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'new'")),
        sa.Column("handled_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("handled_at", sa.DateTime(timezone=True)),
        sa.Column("reject_reason", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("quantity > 0", name="ck_part_requests_quantity"),
        sa.CheckConstraint(
            "status IN ('new','approved','rejected','issued')", name="ck_part_requests_status"
        ),
    )
    op.create_index("ix_part_requests_status_created", "part_requests", ["status", "created_at"])
    op.create_index("ix_part_requests_work_order_id", "part_requests", ["work_order_id"])
    op.execute(
        "CREATE INDEX ix_part_requests_mechanic_created "
        "ON part_requests (mechanic_id, created_at DESC)"
    )

    op.create_table(
        "vehicle_recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("vehicle_id", sa.Uuid(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("work_order_id", sa.Uuid(), sa.ForeignKey("work_orders.id")),
        sa.Column("text", sa.String(1000), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "priority IN ('low','medium','high')", name="ck_vehicle_recommendations_priority"
        ),
        sa.CheckConstraint(
            "status IN ('open','done','declined')", name="ck_vehicle_recommendations_status"
        ),
    )
    op.create_index(
        "ix_vehicle_recommendations_vehicle_status",
        "vehicle_recommendations",
        ["vehicle_id", "status"],
    )

    _grant("work_logs", "SELECT, INSERT, UPDATE")
    _grant("part_requests, vehicle_recommendations", "SELECT, INSERT, UPDATE, DELETE")


def downgrade() -> None:
    op.drop_table("vehicle_recommendations")
    op.drop_table("part_requests")
    op.drop_table("work_logs")
