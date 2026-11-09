"""Отчёты D-02: выручка, услуги, механики, клиенты, склад, расходы, прибыль (модуль 10)."""

import calendar
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, User, UserLocation
from app.models.cash import Expense, ExpenseCategory
from app.models.catalog import Part, Service
from app.models.stock import StockBalance, StockMovement
from app.models.work_order import WorkOrder, WorkOrderItem, WorkOrderPart
from app.schemas.reports import ChartSeries, Report, ReportChart, ReportColumn
from app.services.payroll_calc import months_between, payroll_by_location
from app.services.report_common import (
    ZERO,
    Period,
    dec,
    in_period,
    loc_ids,
    local_day,
    money_s,
    pct_s,
    q2,
    ratio_pct,
    resolve_locations,
    resolve_period,
    today_app,
)
from app.services.report_queries import client_counts, closed_orders, item_net_expr

MAX_ROWS = 500
MAX_SERVICE_ROWS = 200
FREE_WORKS = "Прочие работы (вручную)"
DEPT_RU = {"service": "Сервис", "detailing": "Детейлинг"}

Row = dict[str, str | None]

REPORT_TITLES: dict[str, str] = {
    "revenue": "Выручка по точкам и отделам",
    "services": "Услуги",
    "mechanics": "Механики",
    "clients": "Клиенты",
    "stock": "Склад: оборот и маржа",
    "expenses": "Расходы",
    "profit": "Прибыль",
}
GROUPS: dict[str, tuple[str, ...]] = {
    "revenue": ("location", "day", "month"),
    "clients": ("location", "month"),
    "expenses": ("category", "location", "month"),
}
DEFAULT_GROUP = {"revenue": "location", "clients": "location", "expenses": "category"}


def col(key: str, title: str, kind: str) -> ReportColumn:
    return ReportColumn(key=key, title=title, kind=kind)


def cnt(value: int | Decimal) -> str:
    return str(int(value))


@dataclass
class Result:
    columns: list[ReportColumn]
    rows: list[Row]
    totals: Row | None
    chart: ReportChart | None = None
    truncated: bool = False


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _group_keys(group_by: str, p: Period) -> list[Any]:
    """Непрерывный список ключей группировки по времени."""
    if group_by == "day":
        return [p.date_from + timedelta(days=i) for i in range(p.days)]
    return [_month_key(m) for m in months_between(p.date_from, p.date_to)]


def _time_key(group_by: str, expr: Any) -> Any:
    return expr if group_by == "day" else func.to_char(expr, "YYYY-MM")


# ---------------- выручка ----------------


@dataclass
class _Rev:
    orders: int = 0
    revenue: Decimal = ZERO
    discounts: Decimal = ZERO
    service: Decimal = ZERO
    detailing: Decimal = ZERO
    parts: Decimal = ZERO


def _rev_row(label: str, r: _Rev, extra: Row | None = None) -> Row:
    avg = q2(r.revenue / r.orders) if r.orders else ZERO
    row: Row = {
        "group": label,
        "orders_closed": cnt(r.orders),
        "service_works": money_s(r.service),
        "detailing_works": money_s(r.detailing),
        "parts": money_s(r.parts),
        "discounts": money_s(r.discounts),
        "revenue": money_s(r.revenue),
        "average_check": money_s(avg),
    }
    if extra:
        row.update(extra)
    return row


async def revenue_report(
    session: AsyncSession, locs: list[Location], p: Period, group_by: str, department: str | None
) -> Result:
    ids = loc_ids(locs)
    co = closed_orders(p, ids)
    key = co.c.location_id if group_by == "location" else _time_key(group_by, co.c.day)
    data: dict[Any, _Rev] = {}

    def rec(k: Any) -> _Rev:
        return data.setdefault(k, _Rev())

    for k, orders, revenue, discounts in await session.execute(
        select(key, func.count(), func.sum(co.c.total), func.sum(co.c.discount_total)).group_by(key)
    ):
        r = rec(k)
        r.orders, r.revenue, r.discounts = int(orders), dec(revenue), dec(discounts)
    for k, dept, total in await session.execute(
        select(key, WorkOrderItem.department, func.sum(WorkOrderItem.total))
        .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
        .where(WorkOrderItem.status != "cancelled")
        .group_by(key, WorkOrderItem.department)
    ):
        r = rec(k)
        if dept == "detailing":
            r.detailing += dec(total)
        else:
            r.service += dec(total)
    for k, total in await session.execute(
        select(key, func.sum(WorkOrderPart.total))
        .join(WorkOrderPart, WorkOrderPart.work_order_id == co.c.id)
        .group_by(key)
    ):
        rec(k).parts += dec(total)

    rows: list[Row] = []
    if group_by == "location":
        for loc in locs:
            found = data.get(loc.id)
            if found is None and not loc.is_active:
                continue
            rows.append(_rev_row(loc.name, found or _Rev(), {"location_id": str(loc.id)}))
        rows.sort(key=lambda row: Decimal(row["revenue"] or 0), reverse=True)
    else:
        for k in _group_keys(group_by, p):
            rows.append(_rev_row(k.isoformat() if isinstance(k, date) else k, data.get(k, _Rev())))

    total = _Rev()
    for r in data.values():
        total.orders += r.orders
        total.revenue += r.revenue
        total.discounts += r.discounts
        total.service += r.service
        total.detailing += r.detailing
        total.parts += r.parts
    totals = _rev_row("Итого", total)
    columns = [
        col("group", {"location": "Точка", "day": "День", "month": "Месяц"}[group_by], "text"),
        col("orders_closed", "Закрыто заказов", "count"),
        col("service_works", "Работы (сервис)", "money"),
        col("detailing_works", "Работы (детейлинг)", "money"),
        col("parts", "Запчасти", "money"),
        col("discounts", "Скидки", "money"),
        col("revenue", "Выручка", "money"),
        col("average_check", "Средний чек", "money"),
    ]
    chart = ReportChart(
        type="bar" if group_by == "location" else "line",
        x="group",
        series=[ChartSeries(key="revenue", title="Выручка")],
    )
    return Result(columns, rows, totals, chart)


# ---------------- услуги ----------------


async def services_report(
    session: AsyncSession, locs: list[Location], p: Period, department: str | None
) -> Result:
    co = closed_orders(p, loc_ids(locs))
    filters = [WorkOrderItem.status != "cancelled"]
    if department:
        filters.append(WorkOrderItem.department == department)
    revenue = func.sum(WorkOrderItem.total)
    found = (
        await session.execute(
            select(
                WorkOrderItem.service_id,
                func.min(Service.name),
                func.min(WorkOrderItem.department),
                func.count(distinct(WorkOrderItem.department)),
                func.sum(WorkOrderItem.quantity),
                func.count(distinct(WorkOrderItem.work_order_id)),
                revenue,
            )
            .select_from(co)
            .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
            .outerjoin(Service, Service.id == WorkOrderItem.service_id)
            .where(*filters)
            .group_by(WorkOrderItem.service_id)
        )
    ).all()
    all_orders = (
        await session.scalar(
            select(func.count(distinct(WorkOrderItem.work_order_id)))
            .select_from(co)
            .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
            .where(*filters)
        )
        or 0
    )
    entries = []
    for service_id, name, dept, dept_count, qty, orders, rev in found:
        label = (name or FREE_WORKS) if service_id is not None else FREE_WORKS
        entries.append((service_id, label, dept, int(dept_count), dec(qty), int(orders), dec(rev)))
    entries.sort(key=lambda e: (-e[6], e[1]))
    grand = sum((e[6] for e in entries), ZERO)
    rows: list[Row] = []
    for service_id, label, dept, dept_count, qty, orders, rev in entries[:MAX_SERVICE_ROWS]:
        rows.append(
            {
                "name": label,
                "department": DEPT_RU.get(dept, dept) if dept_count == 1 else "Смешанный",
                "quantity": money_s(qty),
                "orders": cnt(orders),
                "revenue": money_s(rev),
                "share": pct_s(ratio_pct(rev, grand)) or "0.00",
                "service_id": None if service_id is None else str(service_id),
            }
        )
    totals: Row = {
        "name": "Итого",
        "department": None,
        "quantity": money_s(sum((e[4] for e in entries), ZERO)),
        "orders": cnt(all_orders),
        "revenue": money_s(grand),
        "share": "100.00" if grand else "0.00",
    }
    columns = [
        col("name", "Услуга", "text"),
        col("department", "Отдел", "text"),
        col("quantity", "Количество", "count"),
        col("orders", "Заказов", "count"),
        col("revenue", "Выручка", "money"),
        col("share", "Доля", "percent"),
    ]
    return Result(columns, rows, totals, None, len(entries) > MAX_SERVICE_ROWS)


# ---------------- механики ----------------


async def mechanics_report(
    session: AsyncSession, locs: list[Location], p: Period, department: str | None
) -> Result:
    co = closed_orders(p, loc_ids(locs))
    filters = [WorkOrderItem.status == "done", WorkOrderItem.mechanic_id.is_not(None)]
    if department:
        filters.append(WorkOrderItem.department == department)
    works = func.sum(WorkOrderItem.total)
    found = (
        await session.execute(
            select(
                WorkOrderItem.mechanic_id,
                User.full_name,
                func.count(),
                func.sum(func.round(WorkOrderItem.norm_hours * WorkOrderItem.quantity, 2)),
                func.sum(WorkOrderItem.actual_minutes),
                works,
                func.sum(item_net_expr(co)),
            )
            .select_from(co)
            .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
            .join(User, User.id == WorkOrderItem.mechanic_id)
            .where(*filters)
            .group_by(WorkOrderItem.mechanic_id, User.full_name)
            .order_by(works.desc(), User.full_name)
        )
    ).all()
    user_ids = [r[0] for r in found]
    names: dict[uuid.UUID, list[str]] = {}
    if user_ids:
        for uid, name in await session.execute(
            select(UserLocation.user_id, Location.name)
            .join(Location, Location.id == UserLocation.location_id)
            .where(UserLocation.user_id.in_(user_ids))
            .order_by(Location.name)
        ):
            names.setdefault(uid, []).append(name)

    def eff(norm: Decimal, minutes: int) -> str | None:
        return pct_s(ratio_pct(norm * 60, Decimal(minutes)))

    rows: list[Row] = []
    t_items = t_minutes = 0
    t_norm = t_works = t_net = ZERO
    for uid, full_name, n_items, norm, minutes, works_amount, net in found:
        norm_d, minutes_i = q2(dec(norm)), int(minutes or 0)
        t_items += int(n_items)
        t_minutes += minutes_i
        t_norm += norm_d
        t_works += dec(works_amount)
        t_net += dec(net)
        rows.append(
            {
                "mechanic": full_name,
                "locations": ", ".join(names.get(uid, [])),
                "items_done": cnt(n_items),
                "norm_hours": money_s(norm_d),
                "actual_hours": money_s(Decimal(minutes_i) / 60),
                "efficiency": eff(norm_d, minutes_i),
                "works_amount": money_s(dec(works_amount)),
                "net_amount": money_s(dec(net)),
                "user_id": str(uid),
            }
        )
    totals: Row = {
        "mechanic": "Итого",
        "locations": None,
        "items_done": cnt(t_items),
        "norm_hours": money_s(t_norm),
        "actual_hours": money_s(Decimal(t_minutes) / 60),
        "efficiency": eff(t_norm, t_minutes),
        "works_amount": money_s(t_works),
        "net_amount": money_s(t_net),
    }
    columns = [
        col("mechanic", "Механик", "text"),
        col("locations", "Точки", "text"),
        col("items_done", "Работ выполнено", "count"),
        col("norm_hours", "Нормочасы", "hours"),
        col("actual_hours", "Фактические часы", "hours"),
        col("efficiency", "Выработка", "percent"),
        col("works_amount", "Стоимость работ", "money"),
        col("net_amount", "Стоимость работ после скидок", "money"),
    ]
    return Result(columns, rows, totals)


# ---------------- клиенты ----------------


async def _lapsed(session: AsyncSession, ref: date, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Клиенты с заказом за 180–365 суток до `ref` и без заказов за последние 180 суток.

    Относятся к точке их последнего заказа в окне 180–365 суток.
    """
    lo = datetime.combine(ref - timedelta(days=366), time.min, tzinfo=UTC)
    hi = datetime.combine(ref + timedelta(days=2), time.min, tzinfo=UTC)
    day = local_day(WorkOrder.closed_at)
    base = (
        select(
            WorkOrder.client_id.label("client_id"),
            WorkOrder.location_id.label("location_id"),
            WorkOrder.closed_at.label("closed_at"),
            day.label("d"),
        )
        .join(Location, Location.id == WorkOrder.location_id)
        .where(
            WorkOrder.status == "closed",
            WorkOrder.closed_at >= lo,
            WorkOrder.closed_at < hi,
            day >= ref - timedelta(days=365),
            day <= ref,
        )
        .subquery("lapsed_base")
    )
    recent = select(base.c.client_id).where(base.c.d > ref - timedelta(days=180))
    last_old = (
        select(base.c.client_id, base.c.location_id)
        .where(base.c.d <= ref - timedelta(days=180), base.c.client_id.not_in(recent))
        .ext(distinct_on(base.c.client_id))
        .order_by(base.c.client_id, base.c.closed_at.desc())
        .subquery("lapsed_last")
    )
    result: dict[uuid.UUID, int] = {}
    for lid, n in await session.execute(
        select(last_old.c.location_id, func.count())
        .where(last_old.c.location_id.in_(ids))
        .group_by(last_old.c.location_id)
    ):
        result[lid] = int(n)
    return result


async def clients_report(
    session: AsyncSession, locs: list[Location], p: Period, group_by: str
) -> Result:
    ids = loc_ids(locs)
    co = closed_orders(p, ids)
    first = (
        select(WorkOrder.client_id.label("client_id"), WorkOrder.id.label("first_id"))
        .where(WorkOrder.status == "closed", WorkOrder.client_id.in_(select(co.c.client_id)))
        .ext(distinct_on(WorkOrder.client_id))
        .order_by(WorkOrder.client_id, WorkOrder.closed_at, WorkOrder.id)
        .subquery("first_order")
    )
    key = co.c.location_id if group_by == "location" else _time_key("month", co.c.day)
    data: dict[Any, tuple[int, Decimal, int, int]] = {}
    for k, orders, revenue, clients, new in await session.execute(
        select(
            key,
            func.count(co.c.id),
            func.sum(co.c.total),
            func.count(distinct(co.c.client_id)),
            func.count(distinct(case((first.c.first_id.is_not(None), co.c.client_id)))),
        )
        .select_from(co)
        .outerjoin(first, first.c.first_id == co.c.id)
        .group_by(key)
    ):
        data[k] = (int(orders), dec(revenue), int(new), int(clients) - int(new))

    lapsed_by_loc: dict[uuid.UUID, int] = {}
    lapsed_month: dict[str, int] = {}
    if group_by == "location":
        lapsed_by_loc = await _lapsed(session, p.date_to, ids)
    else:
        for month in months_between(p.date_from, p.date_to):
            end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
            lapsed_month[_month_key(month)] = sum(
                (await _lapsed(session, min(end, p.date_to), ids)).values()
            )

    def row(label: str, orders: int, revenue: Decimal, new: int, repeat: int, lapsed: int) -> Row:
        avg = q2(revenue / orders) if orders else ZERO
        return {
            "group": label,
            "new_clients": cnt(new),
            "repeat_clients": cnt(repeat),
            "orders_closed": cnt(orders),
            "average_check": money_s(avg),
            "lapsed_clients": cnt(lapsed),
        }

    rows: list[Row] = []
    if group_by == "location":
        for loc in locs:
            d = data.get(loc.id)
            lapsed = lapsed_by_loc.get(loc.id, 0)
            if d is None and not loc.is_active and not lapsed:
                continue
            orders, revenue, new, repeat = d or (0, ZERO, 0, 0)
            rows.append(
                row(loc.name, orders, revenue, new, repeat, lapsed) | {"location_id": str(loc.id)}
            )
    else:
        for k in _group_keys("month", p):
            orders, revenue, new, repeat = data.get(k, (0, ZERO, 0, 0))
            rows.append(row(k, orders, revenue, new, repeat, lapsed_month.get(k, 0)))

    new_total, repeat_total = await client_counts(session, co)
    orders_total = sum(v[0] for v in data.values())
    revenue_total = sum((v[1] for v in data.values()), ZERO)
    lapsed_total = (
        sum((await _lapsed(session, p.date_to, ids)).values())
        if group_by != "location"
        else sum(lapsed_by_loc.values())
    )
    totals = row("Итого", orders_total, revenue_total, new_total, repeat_total, lapsed_total)
    columns = [
        col("group", "Точка" if group_by == "location" else "Месяц", "text"),
        col("new_clients", "Новые клиенты", "count"),
        col("repeat_clients", "Повторные клиенты", "count"),
        col("orders_closed", "Закрыто заказов", "count"),
        col("average_check", "Средний чек", "money"),
        col("lapsed_clients", "Ушедшие клиенты", "count"),
    ]
    chart = ReportChart(
        type="bar",
        x="group",
        series=[
            ChartSeries(key="new_clients", title="Новые клиенты"),
            ChartSeries(key="repeat_clients", title="Повторные клиенты"),
        ],
    )
    return Result(columns, rows, totals, chart)


# ---------------- склад ----------------


async def stock_report(session: AsyncSession, locs: list[Location], p: Period) -> Result:
    ids = loc_ids(locs)
    co = closed_orders(p, ids)
    sold: dict[uuid.UUID, tuple[Decimal, Decimal, Decimal]] = {}
    for part_id, qty, revenue, cost in await session.execute(
        select(
            WorkOrderPart.part_id,
            func.sum(WorkOrderPart.quantity),
            func.sum(WorkOrderPart.total),
            func.sum(WorkOrderPart.quantity * func.coalesce(WorkOrderPart.unit_cost, 0)),
        )
        .select_from(co)
        .join(WorkOrderPart, WorkOrderPart.work_order_id == co.c.id)
        .where(WorkOrderPart.part_id.is_not(None))
        .group_by(WorkOrderPart.part_id)
    ):
        assert part_id is not None  # отфильтровано условием part_id IS NOT NULL
        sold[part_id] = (dec(qty), dec(revenue), dec(cost))
    received: dict[uuid.UUID, Decimal] = {}
    for part_id, value in await session.execute(
        select(StockMovement.part_id, func.sum(StockMovement.quantity * StockMovement.unit_cost))
        .join(Location, Location.id == StockMovement.location_id)
        .where(
            StockMovement.movement_type == "receipt",
            StockMovement.location_id.in_(ids),
            *in_period(StockMovement.created_at, p),
        )
        .group_by(StockMovement.part_id)
    ):
        received[part_id] = dec(value)
    on_hand: dict[uuid.UUID, Decimal] = {}
    for part_id, value in await session.execute(
        select(StockBalance.part_id, func.sum(StockBalance.quantity * StockBalance.avg_cost))
        .where(StockBalance.location_id.in_(ids), StockBalance.quantity > 0)
        .group_by(StockBalance.part_id)
    ):
        on_hand[part_id] = dec(value)

    part_ids = set(sold) | set(received) | {k for k, v in on_hand.items() if v}
    info: dict[uuid.UUID, tuple[str, str]] = {}
    if part_ids:
        for pid, sku, name in await session.execute(
            select(Part.id, Part.sku, Part.name).where(Part.id.in_(part_ids))
        ):
            info[pid] = (sku, name)
    ordered = sorted(
        (pid for pid in part_ids if pid in info),
        key=lambda pid: (
            -sold.get(pid, (ZERO, ZERO, ZERO))[1],
            -on_hand.get(pid, ZERO),
            info[pid][1],
        ),
    )

    def row(
        label: str,
        sku: str | None,
        qty: Decimal,
        rev: Decimal,
        cost: Decimal,
        rec: Decimal,
        val: Decimal,
    ) -> Row:
        margin = rev - cost
        return {
            "part": label,
            "sku": sku,
            "sold_quantity": f"{qty:.3f}",
            "revenue": money_s(rev),
            "cost": money_s(cost),
            "margin": money_s(margin),
            "margin_percent": pct_s(ratio_pct(margin, rev)),
            "received_value": money_s(rec),
            "stock_value": money_s(val),
        }

    rows = [
        row(
            info[pid][1],
            info[pid][0],
            *sold.get(pid, (ZERO, ZERO, ZERO)),
            received.get(pid, ZERO),
            on_hand.get(pid, ZERO),
        )
        | {"part_id": str(pid)}
        for pid in ordered[:MAX_ROWS]
    ]
    totals = row(
        "Итого",
        None,
        sum((v[0] for v in sold.values()), ZERO),
        sum((v[1] for v in sold.values()), ZERO),
        sum((v[2] for v in sold.values()), ZERO),
        sum(received.values(), ZERO),
        sum(on_hand.values(), ZERO),
    )
    columns = [
        col("part", "Запчасть", "text"),
        col("sku", "Артикул", "text"),
        col("sold_quantity", "Продано", "count"),
        col("revenue", "Выручка", "money"),
        col("cost", "Себестоимость", "money"),
        col("margin", "Маржа", "money"),
        col("margin_percent", "Маржа, %", "percent"),
        col("received_value", "Приход", "money"),
        col("stock_value", "Остаток по себестоимости", "money"),
    ]
    return Result(columns, rows, totals, None, len(ordered) > MAX_ROWS)


# ---------------- расходы ----------------


async def _expenses_by_location(
    session: AsyncSession, ids: list[uuid.UUID], p: Period
) -> dict[uuid.UUID, Decimal]:
    return {
        lid: dec(total)
        for lid, total in await session.execute(
            select(Expense.location_id, func.sum(Expense.amount))
            .where(
                Expense.location_id.in_(ids),
                Expense.cancelled_at.is_(None),
                Expense.expense_date >= p.date_from,
                Expense.expense_date <= p.date_to,
            )
            .group_by(Expense.location_id)
        )
    }


async def expenses_report(
    session: AsyncSession, locs: list[Location], p: Period, group_by: str
) -> Result:
    ids = loc_ids(locs)
    base = [
        Expense.location_id.in_(ids),
        Expense.cancelled_at.is_(None),
        Expense.expense_date >= p.date_from,
        Expense.expense_date <= p.date_to,
    ]
    total = func.sum(Expense.amount)
    extra_key = (
        "location_id"
        if group_by == "location"
        else "category_id"
        if group_by == "category"
        else None
    )
    if group_by == "category":
        stmt = (
            select(ExpenseCategory.name, func.count(), total, ExpenseCategory.id)
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(*base)
            .group_by(ExpenseCategory.id, ExpenseCategory.name)
            .order_by(total.desc(), ExpenseCategory.name)
        )
    elif group_by == "location":
        stmt = (
            select(Location.name, func.count(), total, Location.id)
            .join(Location, Location.id == Expense.location_id)
            .where(*base)
            .group_by(Location.id, Location.name)
            .order_by(total.desc(), Location.name)
        )
    else:
        month = func.to_char(Expense.expense_date, "YYYY-MM")
        stmt = (
            select(month, func.count(), total, month).where(*base).group_by(month).order_by(month)
        )
    rows: list[Row] = []
    t_count, t_total = 0, ZERO
    for label, n, amount, ref in await session.execute(stmt):
        t_count += int(n)
        t_total += dec(amount)
        row: Row = {"group": label, "count": cnt(n), "total": money_s(dec(amount))}
        if extra_key:
            row[extra_key] = str(ref)
        rows.append(row)
    truncated = len(rows) > MAX_ROWS
    columns = [
        col(
            "group",
            {"category": "Категория", "location": "Точка", "month": "Месяц"}[group_by],
            "text",
        ),
        col("count", "Количество", "count"),
        col("total", "Сумма", "money"),
    ]
    totals: Row = {"group": "Итого", "count": cnt(t_count), "total": money_s(t_total)}
    chart = ReportChart(type="bar", x="group", series=[ChartSeries(key="total", title="Сумма")])
    return Result(columns, rows[:MAX_ROWS], totals, chart, truncated)


# ---------------- прибыль ----------------


def _month_aligned(p: Period) -> None:
    last = calendar.monthrange(p.date_to.year, p.date_to.month)[1]
    fields: dict[str, str] = {}
    if p.date_from.day != 1:
        fields["date_from"] = "not_month_start"
    if p.date_to.day != last:
        fields["date_to"] = "not_month_end"
    if fields:
        raise AppError(422, "validation_error", fields)


async def profit_report(session: AsyncSession, locs: list[Location], p: Period) -> Result:
    _month_aligned(p)
    ids = loc_ids(locs)
    co = closed_orders(p, ids)
    revenue: dict[uuid.UUID, Decimal] = {
        lid: dec(v)
        for lid, v in await session.execute(
            select(co.c.location_id, func.sum(co.c.total)).group_by(co.c.location_id)
        )
    }
    parts_cost: dict[uuid.UUID, Decimal] = {
        lid: dec(v)
        for lid, v in await session.execute(
            select(
                co.c.location_id,
                func.sum(WorkOrderPart.quantity * func.coalesce(WorkOrderPart.unit_cost, 0)),
            )
            .join(WorkOrderPart, WorkOrderPart.work_order_id == co.c.id)
            .group_by(co.c.location_id)
        )
    }
    payroll_all = await payroll_by_location(session, p.date_from, p.date_to)
    expenses = await _expenses_by_location(session, ids, p)

    def row(label: str, rev: Decimal, cost: Decimal, pay: Decimal, exp: Decimal) -> Row:
        profit = rev - cost - pay - exp
        return {
            "group": label,
            "revenue": money_s(rev),
            "parts_cost": money_s(cost),
            "payroll": money_s(pay),
            "expenses": money_s(exp),
            "profit": money_s(profit),
            "margin_percent": pct_s(ratio_pct(profit, rev)),
        }

    rows: list[Row] = []
    sums = [ZERO, ZERO, ZERO, ZERO]
    for loc in locs:
        vals = (
            revenue.get(loc.id, ZERO),
            parts_cost.get(loc.id, ZERO),
            payroll_all.get(loc.id, ZERO),
            expenses.get(loc.id, ZERO),
        )
        if not loc.is_active and not any(vals):
            continue
        for i, v in enumerate(vals):
            sums[i] += v
        rows.append(row(loc.name, *vals) | {"location_id": str(loc.id)})
    columns = [
        col("group", "Точка", "text"),
        col("revenue", "Выручка", "money"),
        col("parts_cost", "Себестоимость запчастей", "money"),
        col("payroll", "Зарплата", "money"),
        col("expenses", "Расходы", "money"),
        col("profit", "Прибыль", "money"),
        col("margin_percent", "Рентабельность", "percent"),
    ]
    chart = ReportChart(
        type="bar",
        x="group",
        series=[
            ChartSeries(key="revenue", title="Выручка"),
            ChartSeries(key="profit", title="Прибыль"),
        ],
    )
    return Result(columns, rows, row("Итого", *sums), chart)


# ---------------- сборка ----------------


def check_report_id(report_id: str) -> None:
    if report_id not in REPORT_TITLES:
        raise AppError(404, "not_found")


async def build_report(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    report_id: str,
    *,
    location_id: uuid.UUID | None,
    department: str | None,
    group_by: str | None,
    date_from: date | None,
    date_to: date | None,
) -> Report:
    check_report_id(report_id)
    if group_by is not None and group_by not in GROUPS.get(report_id, ()):
        raise AppError(422, "validation_error", {"group_by": "invalid"})
    group = group_by or DEFAULT_GROUP.get(report_id, "")
    if report_id == "profit" and date_to is None:
        base = date_from or today_app()
        date_to = date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])
    p = resolve_period(date_from, date_to)
    locs = await resolve_locations(session, actor, allowed, location_id)

    runners: dict[str, Callable[[], Coroutine[Any, Any, Result]]] = {
        "revenue": lambda: revenue_report(session, locs, p, group, department),
        "services": lambda: services_report(session, locs, p, department),
        "mechanics": lambda: mechanics_report(session, locs, p, department),
        "clients": lambda: clients_report(session, locs, p, group),
        "stock": lambda: stock_report(session, locs, p),
        "expenses": lambda: expenses_report(session, locs, p, group),
        "profit": lambda: profit_report(session, locs, p),
    }
    result = await runners[report_id]()
    truncated = result.truncated or len(result.rows) > MAX_ROWS
    return Report(
        id=report_id,
        title=REPORT_TITLES[report_id],
        date_from=p.date_from,
        date_to=p.date_to,
        location_id=location_id,
        columns=result.columns,
        rows=result.rows[:MAX_ROWS],
        totals=result.totals,
        chart=result.chart,
        truncated=truncated,
        generated_at=datetime.now(UTC),
    )
