import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

MOVEMENT_TYPES = (
    "receipt",
    "issue_to_order",
    "return_from_order",
    "write_off",
    "transfer_out",
    "transfer_in",
    "adjustment",
)


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_stock_balances_quantity"),
        CheckConstraint("min_quantity >= 0", name="ck_stock_balances_min_quantity"),
        CheckConstraint("avg_cost >= 0", name="ck_stock_balances_avg_cost"),
        Index("ix_stock_balances_part_id", "part_id"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), primary_key=True)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), server_default=text("0"), default=Decimal(0)
    )
    avg_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default=text("0"), default=Decimal(0)
    )
    min_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), server_default=text("0"), default=Decimal(0)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=func.now()
    )


class StockMovement(Base):
    """Движение склада: только INSERT (права БД + триггер)."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('receipt','issue_to_order','return_from_order','write_off',"
            "'transfer_out','transfer_in','adjustment')",
            name="ck_stock_movements_type",
        ),
        CheckConstraint("quantity <> 0", name="ck_stock_movements_quantity"),
        Index(
            "ix_stock_movements_loc_part_created", "location_id", "part_id", text("created_at DESC")
        ),
        Index("ix_stock_movements_work_order_id", "work_order_id"),
        Index("ix_stock_movements_related", "related_movement_id"),
        Index("ix_stock_movements_loc_created", "location_id", text("created_at DESC")),
        Index(
            "uq_stock_movements_single_reversal",
            "related_movement_id",
            unique=True,
            postgresql_where=text("movement_type = 'adjustment' AND related_movement_id IS NOT NULL"),
        ),
        Index(
            "uq_stock_movements_single_return",
            "related_movement_id",
            unique=True,
            postgresql_where=text("movement_type = 'return_from_order'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id"))
    movement_type: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    # FK на work_orders добавляет миграция 0008 (таблица создаётся модулем 5).
    work_order_id: Mapped[uuid.UUID | None] = mapped_column()
    related_movement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_movements.id"))
    supplier: Mapped[str | None] = mapped_column(String(200))
    document_number: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
