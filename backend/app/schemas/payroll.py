"""Схемы модуля 10: зарплата (схемы оплаты, корректировки, ведомость, заработок механика)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.core.types import Money, SafeText
from app.schemas.audit import UserRef
from app.schemas.catalog import Department
from app.schemas.common import PatchBase, Strict
from app.schemas.reports import LocationRef

PayrollSchemeType = Literal["percent_of_works", "per_norm_hour", "fixed_plus_percent", "fixed"]
ExportFormat = Literal["xlsx", "csv"]

Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
SignedMoney = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]


# ---------------- вход ----------------


class PayrollSchemeCreate(Strict):
    user_id: uuid.UUID
    scheme_type: PayrollSchemeType
    percent: Percent | None = None
    norm_hour_rate: Money | None = None
    fixed_monthly: Money | None = None
    department: Department | None = None
    valid_from: date


class PayrollSchemePatch(PatchBase):
    valid_to: date


class PayrollAdjustmentCreate(Strict):
    user_id: uuid.UUID
    month: Annotated[str, Field(pattern=r"^\d{4}-\d{2}$")]
    amount: SignedMoney
    reason: SafeText(500, 1)  # type: ignore[valid-type]


# ---------------- выход ----------------


class PayrollSchemeRead(Strict):
    id: uuid.UUID
    user: UserRef
    scheme_type: PayrollSchemeType
    percent: str | None
    norm_hour_rate: str | None
    fixed_monthly: str | None
    department: Department | None
    valid_from: date
    valid_to: date | None
    is_current: bool
    description: str
    created_by: UserRef
    created_at: datetime


class PayrollAdjustmentRead(Strict):
    id: uuid.UUID
    user: UserRef
    month: str
    amount: str
    reason: str
    created_by: UserRef
    created_at: datetime


class PayrollRow(Strict):
    user: UserRef
    locations: list[LocationRef]
    scheme_summary: str
    items_done: int
    norm_hours: str
    base_amount: str
    accrued: str
    adjustments_total: str
    total: str
    items_without_scheme: int


class PayrollTotals(Strict):
    items_done: int
    norm_hours: str
    base_amount: str
    accrued: str
    adjustments_total: str
    total: str


class PayrollSheet(Strict):
    month: str
    location_id: uuid.UUID | None
    rows: list[PayrollRow]
    totals: PayrollTotals


class PayrollOrderRef(Strict):
    id: uuid.UUID
    number: str


class PayrollItemLine(Strict):
    item_id: uuid.UUID
    order: PayrollOrderRef
    closed_at: datetime
    name: str
    department: Department
    quantity: str
    norm_hours_total: str
    item_net: str
    scheme_id: uuid.UUID | None
    amount: str


class PayrollFixedLine(Strict):
    scheme_id: uuid.UUID
    days: int
    days_in_month: int
    amount: str


class PayrollDetail(Strict):
    row: PayrollRow
    items: list[PayrollItemLine]
    fixed: list[PayrollFixedLine]
    adjustments: list[PayrollAdjustmentRead]
    schemes: list[PayrollSchemeRead]


# ---------------- заработок механика ----------------


class EarningsAdjustment(Strict):
    amount: str
    reason: str
    created_at: datetime


class AwaitingClose(Strict):
    items_count: int
    norm_hours: str


class EarningsItem(Strict):
    item_id: uuid.UUID
    order: PayrollOrderRef
    plate_number: str | None
    name: str
    norm_hours_total: str
    actual_minutes: int
    finished_at: datetime | None


class EarningsDay(Strict):
    date: date
    items: list[EarningsItem]


class MyEarnings(Strict):
    month: str
    accrued: str
    adjustments_total: str
    total: str
    items_done: int
    norm_hours: str
    actual_hours: str
    adjustments: list[EarningsAdjustment]
    awaiting_close: AwaitingClose
    days: list[EarningsDay]
    server_time: datetime
