import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

_ZERO = text("0")
_TRUE = text("true")


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(12, 2), server_default=_ZERO, default=Decimal(0))


class LocationCounter(Base):
    __tablename__ = "location_counters"
    __table_args__ = (
        CheckConstraint("counter_type IN ('work_order')", name="ck_location_counters_type"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    counter_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_value: Mapped[int] = mapped_column(BigInteger, server_default=_ZERO, default=0)


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(
            "department IN ('service','detailing','mixed')", name="ck_work_orders_dept"
        ),
        CheckConstraint(
            "status IN ('new','diagnostics','awaiting_approval','in_progress',"
            "'awaiting_parts','quality_check','ready','closed','cancelled')",
            name="ck_work_orders_status",
        ),
        CheckConstraint("mileage_in >= 0", name="ck_work_orders_mileage"),
        CheckConstraint(
            "status <> 'cancelled' OR cancel_reason IS NOT NULL", name="ck_work_orders_cancel"
        ),
        CheckConstraint("discount_percent BETWEEN 0 AND 100", name="ck_work_orders_discount"),
        CheckConstraint(
            "payment_status IN ('unpaid','partial','paid','refunded')",
            name="ck_work_orders_payment_status",
        ),
        Index("ix_work_orders_location_status", "location_id", "status"),
        Index("ix_work_orders_location_created", "location_id", text("created_at DESC")),
        Index("ix_work_orders_client_id", "client_id"),
        Index("ix_work_orders_vehicle_id", "vehicle_id"),
        Index("ix_work_orders_manager_id", "manager_id"),
        Index(
            "ix_work_orders_planned_open",
            "planned_ready_at",
            postgresql_where=text("status NOT IN ('closed','cancelled')"),
        ),
        # Отчёты (миграция 0010).
        Index(
            "ix_work_orders_closed_location",
            "location_id",
            "closed_at",
            postgresql_where=text("status = 'closed'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"))
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    department: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'new'"), default="new")
    manager_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    mileage_in: Mapped[int | None] = mapped_column(Integer)
    complaint: Mapped[str | None] = mapped_column(String(2000))
    intake_notes: Mapped[str | None] = mapped_column(String(2000))
    diagnosis: Mapped[str | None] = mapped_column(String(4000))
    planned_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default=_ZERO, default=Decimal(0)
    )
    works_total: Mapped[Decimal] = _money()
    parts_total: Mapped[Decimal] = _money()
    discount_total: Mapped[Decimal] = _money()
    total: Mapped[Decimal] = _money()
    paid_total: Mapped[Decimal] = _money()
    payment_status: Mapped[str] = mapped_column(
        String(10), server_default=text("'unpaid'"), default="unpaid"
    )
    # Версию ведёт сервис вручную: оплаты, таймер и комментарии её не меняют.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkOrderItem(Base):
    __tablename__ = "work_order_items"
    __table_args__ = (
        CheckConstraint("department IN ('service','detailing')", name="ck_work_order_items_dept"),
        CheckConstraint("quantity > 0", name="ck_work_order_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_work_order_items_price"),
        CheckConstraint(
            "discount_percent BETWEEN 0 AND 100", name="ck_work_order_items_discount"
        ),
        CheckConstraint(
            "status IN ('pending','in_progress','paused','done','cancelled')",
            name="ck_work_order_items_status",
        ),
        Index("ix_work_order_items_order", "work_order_id"),
        Index("ix_work_order_items_mechanic_status", "mechanic_id", "status"),
        Index("ix_work_order_items_mechanic_finished", "mechanic_id", "finished_at"),
        # Отчёты (миграция 0010).
        Index(
            "ix_work_order_items_mechanic_done",
            "mechanic_id",
            "finished_at",
            postgresql_where=text("status = 'done'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id"))
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default=_ZERO, default=Decimal(0)
    )
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    norm_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default=_ZERO, default=Decimal(0)
    )
    mechanic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(
        String(15), server_default=text("'pending'"), default="pending"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_minutes: Mapped[int] = mapped_column(Integer, server_default=_ZERO, default=0)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=_ZERO, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkOrderPart(Base):
    __tablename__ = "work_order_parts"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_work_order_parts_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_work_order_parts_price"),
        Index("ix_work_order_parts_order", "work_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    name: Mapped[str] = mapped_column(String(200))
    # Снимки справочника (в контракте WorkOrderPart.sku / unit).
    sku: Mapped[str | None] = mapped_column(String(50))
    unit: Mapped[str | None] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stock_movements.id", name="fk_work_order_parts_stock_movement"), unique=True
    )
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkOrderStatusHistory(Base):
    __tablename__ = "work_order_status_history"
    __table_args__ = (Index("ix_work_order_status_history_order", "work_order_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkOrderComment(Base):
    __tablename__ = "work_order_comments"
    __table_args__ = (Index("ix_work_order_comments_order", "work_order_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_order_items.id"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(2000))
    is_internal: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
