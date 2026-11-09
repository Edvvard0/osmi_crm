import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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

METHODS = ("cash", "card", "transfer", "other")
_METHODS_SQL = "method IN ('cash','card','transfer','other')"


class Payment(Base):
    """Платёж или возврат. Неизменяемая запись: сумма всегда положительна, знак задаёт тип."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("payment_type IN ('payment','refund')", name="ck_payments_type"),
        CheckConstraint("amount > 0", name="ck_payments_amount"),
        CheckConstraint(_METHODS_SQL, name="ck_payments_method"),
        CheckConstraint(
            "payment_type = 'payment' OR comment IS NOT NULL", name="ck_payments_refund_comment"
        ),
        CheckConstraint(
            "payment_type = 'refund' OR refund_of_id IS NULL", name="ck_payments_refund_of_null"
        ),
        CheckConstraint(
            "payment_type = 'payment' OR refund_of_id IS NOT NULL",
            name="ck_payments_refund_of_set",
        ),
        Index("ix_payments_location_paid_at", "location_id", "paid_at"),
        Index("ix_payments_work_order_id", "work_order_id"),
        Index("ix_payments_refund_of_id", "refund_of_id"),
        Index(
            "uq_payments_accepted_by_request",
            "accepted_by",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id"))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    payment_type: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(10))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refund_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    comment: Mapped[str | None] = mapped_column(String(500))
    accepted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    client_request_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"
    __table_args__ = (Index("uq_expense_categories_lower_name", text("lower(name)"), unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount"),
        CheckConstraint(_METHODS_SQL, name="ck_expenses_method"),
        Index("ix_expenses_location_date", "location_id", "expense_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(10))
    expense_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
