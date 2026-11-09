"""Дашборд директора, сводка точки, сводка дня (модуль 10)."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, Role, User, UserLocation
from app.models.appointment import Appointment
from app.models.cash import Payment
from app.models.stock import StockBalance
from app.models.catalog import Part, Service
from app.models.work_order import WorkOrder, WorkOrderItem, WorkOrderPart
from app.schemas.audit import UserRef
from app.schemas.reports import (
    ActiveItem,
    Attention,
    AttentionDiscounts,
    AttentionLowStock,
    AttentionOrder,
    AttentionOverdue,
    AttentionRefunds,
    Dashboard,
    DashboardKpis,
    DashboardPeriod,
    DashboardToday,
    LocationRef,
    LocationRow,
    LocationSummary,
    LowStockItem,
    PartRef,
    RevenuePoint,
    SeriesDepartments,
    SeriesLocation,
    SummaryMechanic,
    SummaryPoint,
    TodayMechanic,
    TopService,
)
from app.services.report_common import (
    FINAL_STATUSES,
    NOT_OVERDUE,
    ZERO,
    Period,
    dec,
    hours_from_minutes,
    in_period,
    int_s,
    kpi_count,
    kpi_money,
    kpi_percent,
    load_percent,
    local_day,
    local_today,
    loc_ids,
    money_s,
    pct_s,
    post_load,
    ratio_pct,
    resolve_locations,
    resolve_period,
    q2,
    tz_of,
    day_bounds,
)
from app.services.report_queries import Metrics, closed_orders, net_payments, period_metrics
from app.services.settings import get_setting

MANUAL_WORKS = "Прочие работы (вручную)"
WEEK_THRESHOLD_DAYS = 92


def _ref(loc: Location) -> LocationRef:
    return LocationRef(id=loc.id, name=loc.name)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ---------------- дашборд ----------------


async def _revenue_series(
    session: AsyncSession, locs: list[Location], p: Period
) -> list[RevenuePoint]:
    ids = loc_ids(locs)
    weekly = p.days > WEEK_THRESHOLD_DAYS

    def bucket(day: date) -> date:
        return _monday(day) if weekly else day

    total: dict[date, dict[uuid.UUID, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    dept: dict[date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    if ids:
        co = closed_orders(p, ids)
        for day, lid, amount in await session.execute(
            select(co.c.day, co.c.location_id, func.sum(co.c.total)).group_by(
                co.c.day, co.c.location_id
            )
        ):
            total[bucket(day)][lid] += dec(amount)
        for day, department, amount in await session.execute(
            select(co.c.day, WorkOrderItem.department, func.sum(WorkOrderItem.total))
            .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
            .where(WorkOrderItem.status != "cancelled")
            .group_by(co.c.day, WorkOrderItem.department)
        ):
            dept[bucket(day)][department] += dec(amount)
        for day, amount in await session.execute(
            select(co.c.day, func.sum(WorkOrderPart.total))
            .join(WorkOrderPart, WorkOrderPart.work_order_id == co.c.id)
            .group_by(co.c.day)
        ):
            dept[bucket(day)]["parts"] += dec(amount)

    start = bucket(p.date_from)
    step = timedelta(days=7 if weekly else 1)
    points: list[RevenuePoint] = []
    day = start
    while day <= p.date_to:
        per_loc = total.get(day, {})
        by_dept = dept.get(day, {})
        points.append(
            RevenuePoint(
                date=day,
                total=money_s(sum(per_loc.values(), ZERO)),
                by_location=[
                    SeriesLocation(location_id=loc.id, total=money_s(per_loc.get(loc.id, ZERO)))
                    for loc in locs
                ],
                by_department=SeriesDepartments(
                    service_works=money_s(by_dept.get("service", ZERO)),
                    detailing_works=money_s(by_dept.get("detailing", ZERO)),
                    parts=money_s(by_dept.get("parts", ZERO)),
                ),
            )
        )
        day += step
    return points


async def _top_services(
    session: AsyncSession, locs: list[Location], p: Period
) -> list[TopService]:
    ids = loc_ids(locs)
    if not ids:
        return []
    co = closed_orders(p, ids)
    revenue = func.sum(WorkOrderItem.total)
    name = func.coalesce(Service.name, MANUAL_WORKS)
    rows = await session.execute(
        select(WorkOrderItem.service_id, name, func.sum(WorkOrderItem.quantity), revenue)
        .select_from(co)
        .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
        .outerjoin(Service, Service.id == WorkOrderItem.service_id)
        .where(WorkOrderItem.status != "cancelled")
        .group_by(WorkOrderItem.service_id, name)
        .order_by(revenue.desc(), name)
        .limit(10)
    )
    return [
        TopService(
            service_id=sid, name=nm, quantity=f"{q2(dec(qty)):.2f}", revenue=money_s(dec(rev))
        )
        for sid, nm, qty, rev in rows
    ]


async def _attention(
    session: AsyncSession, locs: list[Location], p: Period
) -> Attention:
    ids = loc_ids(locs)
    refund_count, refund_total = 0, ZERO
    if ids:
        row = (
            await session.execute(
                select(func.count(), func.sum(Payment.amount))
                .join(Location, Location.id == Payment.location_id)
                .where(
                    Payment.location_id.in_(ids),
                    Payment.payment_type == "refund",
                    *in_period(Payment.paid_at, p),
                )
            )
        ).one()
        refund_count, refund_total = int(row[0]), dec(row[1])
    names = {loc.id: loc for loc in locs}

    threshold = q2(Decimal(str(await get_setting(session, "discount_alert_percent"))))
    big_count, big_items = 0, []
    if ids:
        co = closed_orders(p, ids)
        big_count = int(
            await session.scalar(
                select(func.count()).select_from(co).where(co.c.discount_percent >= threshold)
            )
            or 0
        )
        for oid, number, lid, percent in await session.execute(
            select(co.c.id, co.c.number, co.c.location_id, co.c.discount_percent)
            .where(co.c.discount_percent >= threshold)
            .order_by(co.c.discount_percent.desc(), co.c.closed_at.desc())
            .limit(5)
        ):
            big_items.append(
                AttentionOrder(
                    id=oid, number=number, location=_ref(names[lid]), value=f"{q2(percent):.2f}"
                )
            )

    overdue_count, overdue_items = 0, []
    if ids:
        now = datetime.now(UTC)
        cond = (
            WorkOrder.location_id.in_(ids),
            WorkOrder.planned_ready_at < now,
            WorkOrder.status.notin_(NOT_OVERDUE),
        )
        overdue_count = int(
            await session.scalar(select(func.count()).select_from(WorkOrder).where(*cond)) or 0
        )
        for oid, number, lid, planned in await session.execute(
            select(
                WorkOrder.id, WorkOrder.number, WorkOrder.location_id, WorkOrder.planned_ready_at
            )
            .where(*cond)
            .order_by(WorkOrder.planned_ready_at, WorkOrder.id)
            .limit(5)
        ):
            overdue_items.append(
                AttentionOrder(
                    id=oid,
                    number=number,
                    location=_ref(names[lid]),
                    value=planned.astimezone(UTC).isoformat(),
                )
            )

    low_count, low_items = 0, []
    if ids:
        low = (
            StockBalance.location_id.in_(ids),
            StockBalance.min_quantity > 0,
            StockBalance.quantity < StockBalance.min_quantity,
        )
        low_count = int(
            await session.scalar(select(func.count()).select_from(StockBalance).where(*low)) or 0
        )
        for balance, part in await session.execute(
            select(StockBalance, Part)
            .join(Part, Part.id == StockBalance.part_id)
            .where(*low)
            .order_by(
                (StockBalance.quantity / StockBalance.min_quantity),
                StockBalance.location_id,
                Part.sku,
            )
            .limit(5)
        ):
            low_items.append(
                LowStockItem(
                    location=_ref(names[balance.location_id]),
                    part=PartRef(id=part.id, sku=part.sku, name=part.name),
                    quantity=f"{balance.quantity:.3f}",
                    min_quantity=f"{balance.min_quantity:.3f}",
                )
            )

    return Attention(
        refunds=AttentionRefunds(count=refund_count, total=money_s(refund_total)),
        big_discounts=AttentionDiscounts(
            count=big_count, threshold=f"{threshold:.2f}", items=big_items
        ),
        overdue_orders=AttentionOverdue(count=overdue_count, items=overdue_items),
        low_stock=AttentionLowStock(count=low_count, items=low_items),
    )


def _kpis(cur: Metrics, prev: Metrics) -> DashboardKpis:
    return DashboardKpis(
        revenue=kpi_money(cur.revenue, prev.revenue),
        cash_received=kpi_money(cur.cash, prev.cash),
        orders_closed=kpi_count(cur.orders, prev.orders),
        average_check=kpi_money(cur.average_check, prev.average_check),
        post_load=kpi_percent(cur.post_load, prev.post_load),
        detailing_share=kpi_percent(cur.detailing_share, prev.detailing_share),
        conversion=kpi_percent(cur.conversion, prev.conversion),
        new_clients=kpi_count(cur.new_clients, prev.new_clients),
        repeat_clients=kpi_count(cur.repeat_clients, prev.repeat_clients),
    )


async def dashboard(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    location_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> Dashboard:
    p = resolve_period(date_from, date_to)
    locs = await resolve_locations(session, actor, allowed, location_id)
    cur = await period_metrics(session, locs, p)
    prev = await period_metrics(session, locs, p.previous)
    rows: list[LocationRow] = []
    for loc in locs:
        agg = cur.per_location[loc.id]
        avg = q2(agg.revenue / agg.orders) if agg.orders else ZERO
        rows.append(
            LocationRow(
                location=_ref(loc),
                revenue=money_s(agg.revenue),
                orders_closed=agg.orders,
                average_check=money_s(avg),
                post_load=f"{load_percent(agg.occupied, agg.available):.2f}",
                detailing_share=f"{(ratio_pct(agg.detailing, agg.works) or ZERO):.2f}",
            )
        )
    return Dashboard(
        period=DashboardPeriod(
            date_from=p.date_from,
            date_to=p.date_to,
            previous_from=p.previous.date_from,
            previous_to=p.previous.date_to,
        ),
        location_id=location_id,
        kpis=_kpis(cur, prev),
        revenue_series=await _revenue_series(session, locs, p),
        locations=rows,
        top_services=await _top_services(session, locs, p),
        attention=await _attention(session, locs, p),
    )


# ---------------- сводка точки ----------------


def _summary_period(
    loc: Location, period: str, date_from: date | None, date_to: date | None
) -> Period:
    today = local_today(loc)
    if period == "day":
        return Period(today, today)
    if period == "week":
        return Period(_monday(today), today)
    if period == "month":
        return Period(today.replace(day=1), today)
    return resolve_period(date_from, date_to)


async def location_summary(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    location_id: uuid.UUID | None,
    period: str,
    date_from: date | None,
    date_to: date | None,
) -> LocationSummary:
    if location_id is None:
        if actor.role != Role.director:
            raise AppError(422, "validation_error", {"location_id": "required"})
        first = await session.scalar(select(Location).order_by(Location.name).limit(1))
        if first is None:
            raise AppError(404, "not_found")
        locs = [first]
    else:
        locs = await resolve_locations(session, actor, allowed, location_id)
    loc = locs[0]
    p = _summary_period(loc, period, date_from, date_to)
    m = await period_metrics(session, locs, p)
    agg = m.per_location[loc.id]

    by_day: dict[date, tuple[Decimal, int]] = {}
    co = closed_orders(p, [loc.id])
    for day, revenue, orders in await session.execute(
        select(co.c.day, func.sum(co.c.total), func.count()).group_by(co.c.day)
    ):
        by_day[day] = (dec(revenue), int(orders))
    series = []
    day = p.date_from
    while day <= p.date_to:
        revenue, orders = by_day.get(day, (ZERO, 0))
        series.append(SummaryPoint(date=day, revenue=money_s(revenue), orders=orders))
        day += timedelta(days=1)

    mechanics: list[SummaryMechanic] = []
    norm = func.sum(WorkOrderItem.norm_hours * WorkOrderItem.quantity)
    for user_id, full_name, count, norm_h, minutes, amount in await session.execute(
        select(
            User.id,
            User.full_name,
            func.count(),
            norm,
            func.sum(WorkOrderItem.actual_minutes),
            func.sum(WorkOrderItem.total),
        )
        .select_from(co)
        .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
        .join(User, User.id == WorkOrderItem.mechanic_id)
        .where(WorkOrderItem.status == "done")
        .group_by(User.id, User.full_name)
        .order_by(func.sum(WorkOrderItem.total).desc(), User.full_name)
    ):
        norm_hours, actual = q2(dec(norm_h)), hours_from_minutes(dec(minutes))
        mechanics.append(
            SummaryMechanic(
                user=UserRef(id=user_id, full_name=full_name),
                items_done=int(count),
                norm_hours=f"{norm_hours:.2f}",
                actual_hours=f"{actual:.2f}",
                efficiency=pct_s(ratio_pct(norm_hours, actual)),
                works_amount=money_s(dec(amount)),
            )
        )
    return LocationSummary(
        location=_ref(loc),
        date_from=p.date_from,
        date_to=p.date_to,
        revenue=money_s(agg.revenue),
        orders_closed=agg.orders,
        average_check=money_s(m.average_check),
        post_load=f"{m.post_load:.2f}",
        series=series,
        mechanics=mechanics,
    )


# ---------------- сводка дня ----------------


async def dashboard_today(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    location_id: uuid.UUID | None,
) -> DashboardToday:
    if location_id is None:
        if actor.role == Role.director:
            loc = await session.scalar(select(Location).order_by(Location.name).limit(1))
        elif len(allowed) == 1:
            loc = await session.get(Location, allowed[0])
        else:
            raise AppError(422, "validation_error", {"location_id": "required"})
        if loc is None:
            raise AppError(404, "not_found")
    else:
        loc = (await resolve_locations(session, actor, allowed, location_id))[0]

    now = datetime.now(UTC)
    today = local_today(loc)
    p = Period(today, today)
    lo, hi = day_bounds(today, tz_of(loc.timezone))

    co = closed_orders(p, [loc.id])
    revenue, closed_n = (
        await session.execute(select(func.sum(co.c.total), func.count()).select_from(co))
    ).one()
    cash = await session.scalar(
        select(net_payments()).where(
            Payment.location_id == loc.id, Payment.paid_at >= lo, Payment.paid_at < hi
        )
    )

    counts = (
        await session.execute(
            select(
                func.count().filter(WorkOrder.status.notin_(FINAL_STATUSES)),
                func.count().filter(
                    WorkOrder.planned_ready_at < now, WorkOrder.status.notin_(NOT_OVERDUE)
                ),
                func.count().filter(WorkOrder.status == "ready"),
            ).where(WorkOrder.location_id == loc.id)
        )
    ).one()
    appointments = int(
        await session.scalar(
            select(func.count()).where(
                Appointment.location_id == loc.id,
                Appointment.start_at >= lo,
                Appointment.start_at < hi,
            )
        )
        or 0
    )
    occ, avail = (await post_load(session, [loc], p))[loc.id]
    low_stock = int(
        await session.scalar(
            select(func.count())
            .select_from(StockBalance)
            .where(
                StockBalance.location_id == loc.id,
                StockBalance.min_quantity > 0,
                StockBalance.quantity < StockBalance.min_quantity,
            )
        )
        or 0
    )

    mechanics_rows = (
        await session.execute(
            select(User.id, User.full_name)
            .join(UserLocation, UserLocation.user_id == User.id)
            .where(
                UserLocation.location_id == loc.id,
                User.role == Role.mechanic,
                User.is_active.is_(True),
            )
            .order_by(User.full_name, User.id)
        )
    ).all()
    mech_ids = [row[0] for row in mechanics_rows]
    active: dict[uuid.UUID, ActiveItem] = {}
    in_progress: dict[uuid.UUID, int] = defaultdict(int)
    done_today: dict[uuid.UUID, int] = defaultdict(int)
    if mech_ids:
        for item_id, mech, name, number in await session.execute(
            select(WorkOrderItem.id, WorkOrderItem.mechanic_id, WorkOrderItem.name, WorkOrder.number)
            .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
            .where(
                WorkOrder.location_id == loc.id,
                WorkOrderItem.mechanic_id.in_(mech_ids),
                WorkOrderItem.status == "in_progress",
            )
            .order_by(WorkOrderItem.started_at.desc().nulls_last(), WorkOrderItem.id)
        ):
            in_progress[mech] += 1
            active.setdefault(mech, ActiveItem(item_id=item_id, name=name, order_number=number))
        for mech, n in await session.execute(
            select(WorkOrderItem.mechanic_id, func.count())
            .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
            .where(
                WorkOrder.location_id == loc.id,
                WorkOrderItem.mechanic_id.in_(mech_ids),
                WorkOrderItem.status == "done",
                WorkOrderItem.finished_at >= lo,
                WorkOrderItem.finished_at < hi,
            )
            .group_by(WorkOrderItem.mechanic_id)
        ):
            done_today[mech] = int(n)

    return DashboardToday(
        server_time=now,
        location=_ref(loc),
        date=today,
        revenue_today=money_s(dec(revenue)),
        cash_received_today=money_s(dec(cash)),
        orders_closed_today=int(closed_n),
        orders_open=int(counts[0]),
        overdue=int(counts[1]),
        ready_for_pickup=int(counts[2]),
        appointments_today=appointments,
        post_load_today=f"{load_percent(occ, avail):.2f}",
        low_stock_count=low_stock,
        mechanics=[
            TodayMechanic(
                user=UserRef(id=uid, full_name=name),
                active_item=active.get(uid),
                items_in_progress=in_progress.get(uid, 0),
                items_done_today=done_today.get(uid, 0),
            )
            for uid, name in mechanics_rows
        ],
    )

