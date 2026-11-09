"""Схемы модуля 10: дашборд, сводки, отчёты. Деньги, часы, проценты — строки."""

import uuid
from datetime import date, datetime
from typing import Literal

from app.schemas.audit import UserRef
from app.schemas.common import Strict


class Kpi(Strict):
    kind: Literal["money", "count", "percent"]
    value: str
    previous: str
    delta: str | None


class LocationRef(Strict):
    id: uuid.UUID
    name: str


class DashboardPeriod(Strict):
    date_from: date
    date_to: date
    previous_from: date
    previous_to: date


class DashboardKpis(Strict):
    revenue: Kpi
    cash_received: Kpi
    orders_closed: Kpi
    average_check: Kpi
    post_load: Kpi
    detailing_share: Kpi
    conversion: Kpi
    new_clients: Kpi
    repeat_clients: Kpi


class SeriesLocation(Strict):
    location_id: uuid.UUID
    total: str


class SeriesDepartments(Strict):
    service_works: str
    detailing_works: str
    parts: str


class RevenuePoint(Strict):
    date: date
    total: str
    by_location: list[SeriesLocation]
    by_department: SeriesDepartments


class LocationRow(Strict):
    location: LocationRef
    revenue: str
    orders_closed: int
    average_check: str
    post_load: str
    detailing_share: str


class TopService(Strict):
    service_id: uuid.UUID | None
    name: str
    quantity: str
    revenue: str


class AttentionOrder(Strict):
    id: uuid.UUID
    number: str
    location: LocationRef
    value: str


class AttentionRefunds(Strict):
    count: int
    total: str


class AttentionDiscounts(Strict):
    count: int
    threshold: str
    items: list[AttentionOrder]


class AttentionOverdue(Strict):
    count: int
    items: list[AttentionOrder]


class PartRef(Strict):
    id: uuid.UUID
    sku: str
    name: str


class LowStockItem(Strict):
    location: LocationRef
    part: PartRef
    quantity: str
    min_quantity: str


class AttentionLowStock(Strict):
    count: int
    items: list[LowStockItem]


class Attention(Strict):
    refunds: AttentionRefunds
    big_discounts: AttentionDiscounts
    overdue_orders: AttentionOverdue
    low_stock: AttentionLowStock


class Dashboard(Strict):
    period: DashboardPeriod
    location_id: uuid.UUID | None
    kpis: DashboardKpis
    revenue_series: list[RevenuePoint]
    locations: list[LocationRow]
    top_services: list[TopService]
    attention: Attention


# ---------------- сводка точки ----------------


class SummaryPoint(Strict):
    date: date
    revenue: str
    orders: int


class SummaryMechanic(Strict):
    user: UserRef
    items_done: int
    norm_hours: str
    actual_hours: str
    efficiency: str | None
    works_amount: str


class LocationSummary(Strict):
    location: LocationRef
    date_from: date
    date_to: date
    revenue: str
    orders_closed: int
    average_check: str
    post_load: str
    series: list[SummaryPoint]
    mechanics: list[SummaryMechanic]


# ---------------- сводка дня ----------------


class ActiveItem(Strict):
    item_id: uuid.UUID
    name: str
    order_number: str


class TodayMechanic(Strict):
    user: UserRef
    active_item: ActiveItem | None
    items_in_progress: int
    items_done_today: int


class DashboardToday(Strict):
    server_time: datetime
    location: LocationRef
    date: date
    revenue_today: str
    cash_received_today: str
    orders_closed_today: int
    orders_open: int
    overdue: int
    ready_for_pickup: int
    appointments_today: int
    post_load_today: str
    low_stock_count: int
    mechanics: list[TodayMechanic]


# ---------------- отчёты ----------------

ReportId = Literal["revenue", "services", "mechanics", "clients", "stock", "expenses", "profit"]
ColumnKind = Literal["text", "money", "hours", "count", "percent", "date"]


class ReportColumn(Strict):
    key: str
    title: str
    kind: ColumnKind


class ChartSeries(Strict):
    key: str
    title: str


class ReportChart(Strict):
    type: Literal["line", "bar"]
    x: str
    series: list[ChartSeries]


class Report(Strict):
    id: ReportId
    title: str
    date_from: date
    date_to: date
    location_id: uuid.UUID | None
    columns: list[ReportColumn]
    rows: list[dict[str, str | None]]
    totals: dict[str, str | None] | None
    chart: ReportChart | None
    truncated: bool
    generated_at: datetime
