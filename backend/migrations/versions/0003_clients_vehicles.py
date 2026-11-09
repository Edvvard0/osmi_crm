"""module 2: clients, vehicles

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _trgm(name: str, table: str, column: str) -> None:
    op.create_index(
        name, table, [column], postgresql_using="gin", postgresql_ops={column: "gin_trgm_ops"}
    )


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_type", sa.String(10), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("company_name", sa.String(200)),
        sa.Column("inn", sa.String(12)),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("phone_extra", sa.String(20)),
        sa.Column("email", sa.String(254)),
        sa.Column("source", sa.String(20)),
        sa.Column(
            "discount_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("notes", sa.String(2000)),
        sa.Column("telegram_chat_id", sa.BigInteger()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("client_type IN ('person','company')", name="ck_clients_client_type"),
        sa.CheckConstraint("inn ~ '^\\d{10}(\\d{2})?$'", name="ck_clients_inn"),
        sa.CheckConstraint(
            "source IN ('walk_in','referral','online','ads','repeat','other')",
            name="ck_clients_source",
        ),
        sa.CheckConstraint("discount_percent BETWEEN 0 AND 100", name="ck_clients_discount"),
    )
    op.create_index(
        "uq_clients_phone_active",
        "clients",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    _trgm("ix_clients_full_name_trgm", "clients", "full_name")
    _trgm("ix_clients_phone_trgm", "clients", "phone")
    _trgm("ix_clients_company_name_trgm", "clients", "company_name")

    op.create_table(
        "vehicles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("make", sa.String(50), nullable=False),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("year", sa.SmallInteger()),
        sa.Column("vin", sa.String(17)),
        sa.Column("plate_number", sa.String(12)),
        sa.Column("color", sa.String(30)),
        sa.Column("mileage", sa.Integer()),
        sa.Column("notes", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("year BETWEEN 1950 AND 2100", name="ck_vehicles_year"),
        sa.CheckConstraint("vin ~ '^[A-HJ-NPR-Z0-9]{17}$'", name="ck_vehicles_vin"),
        sa.CheckConstraint("mileage >= 0", name="ck_vehicles_mileage"),
    )
    op.create_index(
        "uq_vehicles_vin_active",
        "vehicles",
        ["vin"],
        unique=True,
        postgresql_where=sa.text("vin IS NOT NULL AND archived_at IS NULL"),
    )
    op.create_index("ix_vehicles_plate_number", "vehicles", ["plate_number"])
    op.create_index("ix_vehicles_client_id", "vehicles", ["client_id"])
    _trgm("ix_vehicles_plate_number_trgm", "vehicles", "plate_number")
    _trgm("ix_vehicles_vin_trgm", "vehicles", "vin")


def downgrade() -> None:
    op.drop_table("vehicles")
    op.drop_table("clients")
