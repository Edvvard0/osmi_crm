"""Модуль 6: таймер механика, заявки на запчасти, рекомендации по авто."""

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
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class WorkLog(Base):
    __tablename__ = "work_logs"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_work_logs_period"),
        # Одна активная работа на механика (гонка двух стартов гасится индексом).
        Index(
            "work_logs_one_active_per_mechanic",
            "mechanic_id",
            unique=True,
            postgresql_where=sql_text("ended_at IS NULL"),
        ),
        Index("ix_work_logs_mechanic_started", "mechanic_id", "started_at"),
        Index("ix_work_logs_item_id", "item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_order_items.id"))
    mechanic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PartRequest(Base):
    __tablename__ = "part_requests"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_part_requests_quantity"),
        CheckConstraint(
            "status IN ('new','approved','rejected','issued')", name="ck_part_requests_status"
        ),
        Index("ix_part_requests_status_created", "status", "created_at"),
        Index("ix_part_requests_work_order_id", "work_order_id"),
        Index("ix_part_requests_mechanic_created", "mechanic_id", sql_text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_order_items.id"))
    mechanic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id"))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    status: Mapped[str] = mapped_column(String(10), server_default=sql_text("'new'"), default="new")
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VehicleRecommendation(Base):
    __tablename__ = "vehicle_recommendations"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low','medium','high')", name="ck_vehicle_recommendations_priority"
        ),
        CheckConstraint(
            "status IN ('open','done','declined')", name="ck_vehicle_recommendations_status"
        ),
        Index("ix_vehicle_recommendations_vehicle_status", "vehicle_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id"))
    text: Mapped[str] = mapped_column(String(1000))
    priority: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), server_default=sql_text("'open'"), default="open")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
