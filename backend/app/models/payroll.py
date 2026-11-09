"""Модуль 10: схемы оплаты и корректировки зарплаты (сама ведомость не хранится)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

SCHEME_TYPES = ("percent_of_works", "per_norm_hour", "fixed_plus_percent", "fixed")


class PayrollScheme(Base):
    __tablename__ = "payroll_schemes"
    __table_args__ = (
        CheckConstraint(
            "scheme_type IN ('percent_of_works','per_norm_hour','fixed_plus_percent','fixed')",
            name="ck_payroll_schemes_type",
        ),
        CheckConstraint(
            "percent IS NULL OR percent BETWEEN 0 AND 100", name="ck_payroll_schemes_percent"
        ),
        CheckConstraint(
            "norm_hour_rate IS NULL OR norm_hour_rate >= 0", name="ck_payroll_schemes_rate"
        ),
        CheckConstraint(
            "fixed_monthly IS NULL OR fixed_monthly >= 0", name="ck_payroll_schemes_fixed"
        ),
        CheckConstraint(
            "department IS NULL OR department IN ('service','detailing')",
            name="ck_payroll_schemes_department",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="ck_payroll_schemes_period"
        ),
        CheckConstraint(
            "(scheme_type = 'percent_of_works' AND percent IS NOT NULL "
            "AND norm_hour_rate IS NULL AND fixed_monthly IS NULL) "
            "OR (scheme_type = 'per_norm_hour' AND norm_hour_rate IS NOT NULL "
            "AND percent IS NULL AND fixed_monthly IS NULL) "
            "OR (scheme_type = 'fixed_plus_percent' AND percent IS NOT NULL "
            "AND fixed_monthly IS NOT NULL AND norm_hour_rate IS NULL AND department IS NULL) "
            "OR (scheme_type = 'fixed' AND fixed_monthly IS NOT NULL "
            "AND percent IS NULL AND norm_hour_rate IS NULL AND department IS NULL)",
            name="ck_payroll_schemes_fields",
        ),
        ExcludeConstraint(
            ("user_id", "="),
            (text("coalesce(department, '*')"), "="),
            (text("daterange(valid_from, valid_to, '[]')"), "&&"),
            name="payroll_schemes_no_overlap",
            using="gist",
        ),
        Index("ix_payroll_schemes_user_from", "user_id", "valid_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    scheme_type: Mapped[str] = mapped_column(String(20))
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    norm_hour_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fixed_monthly: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    department: Mapped[str | None] = mapped_column(String(10))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayrollAdjustment(Base):
    """Премия (+) или удержание (−). Неизменяемая запись: ошибка исправляется обратной записью."""

    __tablename__ = "payroll_adjustments"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_payroll_adjustments_amount"),
        CheckConstraint("extract(day FROM period_month) = 1", name="ck_payroll_adjustments_month"),
        Index("ix_payroll_adjustments_user_month", "user_id", "period_month"),
        Index("ix_payroll_adjustments_month", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    period_month: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
