"""module 3: service catalog, location prices, work posts, parts

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NOW = sa.text("now()")
TRUE = sa.text("true")
ZERO = sa.text("0")


def _trgm(name: str, table: str, column: str) -> None:
    op.create_index(
        name, table, [column], postgresql_using="gin", postgresql_ops={column: "gin_trgm_ops"}
    )


def upgrade() -> None:
    op.create_table(
        "service_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default=ZERO),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=TRUE),
        sa.CheckConstraint(
            "department IN ('service','detailing')", name="ck_service_categories_dept"
        ),
        sa.UniqueConstraint("department", "name", name="uq_service_categories_dept_name"),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("service_categories.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("norm_hours", sa.Numeric(5, 2), nullable=False, server_default=ZERO),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=TRUE),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("department IN ('service','detailing')", name="ck_services_department"),
        sa.CheckConstraint("unit IN ('pcs','hour','set','sqm')", name="ck_services_unit"),
        sa.CheckConstraint("base_price >= 0", name="ck_services_base_price"),
        sa.CheckConstraint("norm_hours >= 0", name="ck_services_norm_hours"),
        sa.CheckConstraint("duration_minutes > 0", name="ck_services_duration"),
    )
    op.create_index("ix_services_category_id", "services", ["category_id"])
    op.create_index("ix_services_department", "services", ["department"])
    _trgm("ix_services_name_trgm", "services", "name")
    _trgm("ix_services_code_trgm", "services", "code")

    op.create_table(
        "service_location_prices",
        sa.Column(
            "service_id",
            sa.Uuid(),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), primary_key=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("price >= 0", name="ck_service_location_prices_price"),
    )
    op.create_index(
        "ix_service_location_prices_location_id", "service_location_prices", ["location_id"]
    )

    op.create_table(
        "work_posts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("location_id", sa.Uuid(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("post_type", sa.String(20), nullable=False),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False, server_default=ZERO),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=TRUE),
        sa.CheckConstraint(
            "post_type IN ('lift','diagnostics','detailing_box','wash','other')",
            name="ck_work_posts_post_type",
        ),
        sa.CheckConstraint(
            "department IN ('service','detailing')", name="ck_work_posts_department"
        ),
        sa.UniqueConstraint("location_id", "name", name="uq_work_posts_location_name"),
    )

    op.create_table(
        "parts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sku", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(100)),
        sa.Column("barcode", sa.String(50)),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("department", sa.String(10), nullable=False),
        sa.Column("sale_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=TRUE),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("unit IN ('pcs','l','ml','kg','g','m','set')", name="ck_parts_unit"),
        sa.CheckConstraint(
            "department IN ('service','detailing','both')", name="ck_parts_department"
        ),
        sa.CheckConstraint("sale_price >= 0", name="ck_parts_sale_price"),
    )
    op.create_index(
        "uq_parts_barcode",
        "parts",
        ["barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    _trgm("ix_parts_name_trgm", "parts", "name")
    _trgm("ix_parts_sku_trgm", "parts", "sku")


def downgrade() -> None:
    op.drop_table("parts")
    op.drop_table("work_posts")
    op.drop_table("service_location_prices")
    op.drop_table("services")
    op.drop_table("service_categories")
