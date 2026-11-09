import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


def _trgm(name: str, column: str) -> Index:
    return Index(name, column, postgresql_using="gin", postgresql_ops={column: "gin_trgm_ops"})


class ServiceCategory(Base):
    __tablename__ = "service_categories"
    __table_args__ = (
        CheckConstraint("department IN ('service','detailing')", name="ck_service_categories_dept"),
        UniqueConstraint("department", "name", name="uq_service_categories_dept_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    department: Mapped[str] = mapped_column(String(10))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("department IN ('service','detailing')", name="ck_services_department"),
        CheckConstraint("unit IN ('pcs','hour','set','sqm')", name="ck_services_unit"),
        CheckConstraint("base_price >= 0", name="ck_services_base_price"),
        CheckConstraint("norm_hours >= 0", name="ck_services_norm_hours"),
        CheckConstraint("duration_minutes > 0", name="ck_services_duration"),
        Index("ix_services_category_id", "category_id"),
        Index("ix_services_department", "department"),
        _trgm("ix_services_name_trgm", "name"),
        _trgm("ix_services_code_trgm", "code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_categories.id"))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    department: Mapped[str] = mapped_column(String(10))
    unit: Mapped[str] = mapped_column(String(10))
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    norm_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default=text("0"), default=Decimal(0)
    )
    duration_minutes: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ServiceLocationPrice(Base):
    __tablename__ = "service_location_prices"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_service_location_prices_price"),
        Index("ix_service_location_prices_location_id", "location_id"),
    )

    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkPost(Base):
    __tablename__ = "work_posts"
    __table_args__ = (
        CheckConstraint(
            "post_type IN ('lift','diagnostics','detailing_box','wash','other')",
            name="ck_work_posts_post_type",
        ),
        CheckConstraint("department IN ('service','detailing')", name="ck_work_posts_department"),
        UniqueConstraint("location_id", "name", name="uq_work_posts_location_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    name: Mapped[str] = mapped_column(String(50))
    post_type: Mapped[str] = mapped_column(String(20))
    department: Mapped[str] = mapped_column(String(10))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint("unit IN ('pcs','l','ml','kg','g','m','set')", name="ck_parts_unit"),
        CheckConstraint("department IN ('service','detailing','both')", name="ck_parts_department"),
        CheckConstraint("sale_price >= 0", name="ck_parts_sale_price"),
        Index(
            "uq_parts_barcode", "barcode", unique=True, postgresql_where=text("barcode IS NOT NULL")
        ),
        _trgm("ix_parts_name_trgm", "name"),
        _trgm("ix_parts_sku_trgm", "sku"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str | None] = mapped_column(String(100))
    barcode: Mapped[str | None] = mapped_column(String(50))
    unit: Mapped[str] = mapped_column(String(10))
    department: Mapped[str] = mapped_column(String(10))
    sale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
