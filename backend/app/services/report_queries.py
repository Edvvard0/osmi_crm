"""Общие запросы отчётов: закрытые заказы периода, показатели по точкам, клиенты."""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Subquery, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location
from app.models.appointment import Appointment
from app.models.cash import Payment
from app.models.work_order import WorkOrder, WorkOrderItem
from app.services.report_common import (
    ZERO,
    Period,
    dec,
    in_period,
    load_percent,
    local_day,
    loc_ids,
    post_load,
    ratio_pct,
    q2,
)


def closed_orders(p: Period, ids: list[uuid.UUID] | None, name: str = "co") -> Subquery:
    """Закрытые заказы с `closed_at` в периоде (день — по поясу точки заказа)."""
    return (
        select(
            WorkOrder.id.label("id"),
            WorkOrder.number.label("number"),
            WorkOrder.location_id.label("location_id"),
            local_day(WorkOrder.closed_at).label("day"),
            WorkOrder.total.label("total"),
            WorkOrder.discount_total.label("discount_total"),
            WorkOrder.discount_percent.label("discount_percent"),
            WorkOrder.client_id.label("client_id"),
            WorkOrder.vehicle_id.label("vehicle_id"),
            WorkOrder.closed_at.label("closed_at"),
        )
        .join(Location, Location.id == WorkOrder.location_id)
        .where(
            WorkOrder.status == "closed",
            *([WorkOrder.location_id.in_(ids)] if ids is not None else []),
            *in_period(WorkOrder.closed_at, p),
        )
        .subquery(name)
    )


def net_payments() -> Any:
    """Чистые поступления: платежи минус возвраты."""
    return func.sum(case((Payment.payment_type == "refund", -Payment.amount), else_=Payment.amount))


def item_net_expr(co: Subquery) -> Any:
    """Чистая стоимость работы: ROUND(item.total × (1 − скидка заказа / 100), 2)."""
    return func.round(WorkOrderItem.total * (1 - co.c.discount_percent / 100), 2)


@dataclass
class LocAgg:
    revenue: Decimal = ZERO
    orders: int = 0
    detailing: Decimal = ZERO
    works: Decimal = ZERO
    occupied: Decimal = ZERO
    available: Decimal = ZERO


@dataclass
class Metrics:
    per_location: dict[uuid.UUID, LocAgg] = field(default_factory=dict)
    cash: Decimal = ZERO
    arrived: int = 0
    no_show: int = 0
    new_clients: int = 0
    repeat_clients: int = 0

    @property
    def revenue(self) -> Decimal:
        return sum((a.revenue for a in self.per_location.values()), ZERO)

    @property
    def orders(self) -> int:
        return sum(a.orders for a in self.per_location.values())

    @property
    def average_check(self) -> Decimal:
        return q2(self.revenue / self.orders) if self.orders else ZERO

    @property
    def detailing_share(self) -> Decimal:
        detailing = sum((a.detailing for a in self.per_location.values()), ZERO)
        works = sum((a.works for a in self.per_location.values()), ZERO)
        return ratio_pct(detailing, works) or ZERO

    @property
    def post_load(self) -> Decimal:
        occ = sum((a.occupied for a in self.per_location.values()), ZERO)
        avail = sum((a.available for a in self.per_location.values()), ZERO)
        return load_percent(occ, avail)

    @property
    def conversion(self) -> Decimal:
        return ratio_pct(Decimal(self.arrived), Decimal(self.arrived + self.no_show)) or ZERO


async def client_counts(session: AsyncSession, co: Subquery) -> tuple[int, int]:
    """(новые, повторные) клиенты среди клиентов с закрытым заказом в `co`."""
    first = (
        select(WorkOrder.client_id.label("client_id"), func.min(WorkOrder.closed_at).label("at"))
        .where(WorkOrder.status == "closed", WorkOrder.client_id.in_(select(co.c.client_id)))
        .group_by(WorkOrder.client_id)
        .subquery("first_order")
    )
    total = await session.scalar(select(func.count(func.distinct(co.c.client_id)))) or 0
    new = (
        await session.scalar(
            select(func.count(func.distinct(co.c.client_id))).join(
                first, (first.c.client_id == co.c.client_id) & (first.c.at == co.c.closed_at)
            )
        )
        or 0
    )
    return int(new), int(total) - int(new)


async def period_metrics(session: AsyncSession, locs: list[Location], p: Period) -> Metrics:
    ids = loc_ids(locs)
    m = Metrics(per_location={lid: LocAgg() for lid in ids})
    if not ids:
        return m
    co = closed_orders(p, ids)

    for lid, revenue, orders in await session.execute(
        select(co.c.location_id, func.sum(co.c.total), func.count()).group_by(co.c.location_id)
    ):
        m.per_location[lid].revenue = dec(revenue)
        m.per_location[lid].orders = int(orders)

    for lid, dept, total in await session.execute(
        select(co.c.location_id, WorkOrderItem.department, func.sum(WorkOrderItem.total))
        .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
        .where(WorkOrderItem.status != "cancelled")
        .group_by(co.c.location_id, WorkOrderItem.department)
    ):
        agg = m.per_location[lid]
        agg.works += dec(total)
        if dept == "detailing":
            agg.detailing += dec(total)

    m.cash = dec(
        await session.scalar(
            select(net_payments())
            .join(Location, Location.id == Payment.location_id)
            .where(Payment.location_id.in_(ids), *in_period(Payment.paid_at, p))
        )
    )

    for lid, (occ, avail) in (await post_load(session, locs, p)).items():
        m.per_location[lid].occupied = occ
        m.per_location[lid].available = avail

    for status, n in await session.execute(
        select(Appointment.status, func.count())
        .join(Location, Location.id == Appointment.location_id)
        .where(
            Appointment.location_id.in_(ids),
            Appointment.status.in_(("arrived", "no_show")),
            *in_period(Appointment.start_at, p),
        )
        .group_by(Appointment.status)
    ):
        if status == "arrived":
            m.arrived = int(n)
        else:
            m.no_show = int(n)

    m.new_clients, m.repeat_clients = await client_counts(session, co)
    return m
