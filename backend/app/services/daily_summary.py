"""Ежедневная сводка директору (модуль 10): расчёт и публикация события report.daily_summary."""

import re
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location
from app.models.cash import Payment
from app.models.work_order import WorkOrder
from app.services import events
from app.services.payroll_calc import fmt_rub
from app.services.report_common import (
    FINAL_STATUSES,
    ZERO,
    Period,
    app_tz,
    day_bounds,
    dec,
    local_today,
    money_s,
    tz_of,
)
from app.services.report_queries import closed_orders, net_payments
from app.services.settings import get_setting

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
EVENT = "report.daily_summary"


def parse_summary_time(value: object) -> time | None:
    """`HH:MM` -> time; `null` и неверные значения отключают сводку."""
    if not isinstance(value, str):
        return None
    m = _HHMM.match(value)
    return time(int(m.group(1)), int(m.group(2))) if m else None


def orders_word(n: int) -> str:
    """Склонение «заказ» по числу."""
    if 11 <= n % 100 <= 14:
        return "заказов"
    return {1: "заказ", 2: "заказа", 3: "заказа", 4: "заказа"}.get(n % 10, "заказов")


async def build_payload(session: AsyncSession) -> dict[str, str | int | None]:
    """Итоги дня по каждой активной точке («сегодня» по её поясу) и суммы по сети."""
    locs = (
        await session.scalars(
            select(Location).where(Location.is_active.is_(True)).order_by(Location.name)
        )
    ).all()
    revenue = cash = ZERO
    closed = opened = 0
    lines: list[str] = []
    for loc in locs:
        today = local_today(loc)
        lo, hi = day_bounds(today, tz_of(loc.timezone))
        co = closed_orders(Period(today, today), [loc.id])
        loc_revenue, loc_closed = (
            await session.execute(select(func.sum(co.c.total), func.count()).select_from(co))
        ).one()
        loc_cash = await session.scalar(
            select(net_payments()).where(
                Payment.location_id == loc.id, Payment.paid_at >= lo, Payment.paid_at < hi
            )
        )
        loc_open = await session.scalar(
            select(func.count()).where(
                WorkOrder.location_id == loc.id, WorkOrder.status.notin_(FINAL_STATUSES)
            )
        )
        loc_revenue, loc_cash = dec(loc_revenue), dec(loc_cash)
        revenue += loc_revenue
        cash += loc_cash
        closed += int(loc_closed)
        opened += int(loc_open or 0)
        lines.append(
            f"{loc.name}: {fmt_rub(loc_revenue)} · {int(loc_closed)} {orders_word(int(loc_closed))}"
            f" · касса {fmt_rub(loc_cash)}"
        )
    return {
        "date": datetime.now(app_tz()).date().isoformat(),
        "location_name": None,
        "revenue": money_s(revenue),
        "orders_closed": closed,
        "orders_open": opened,
        "cash_received": money_s(cash),
        "breakdown": "\n".join(lines),
    }


async def publish_summary(session: AsyncSession, day: date) -> None:
    payload = await build_payload(session)
    payload["date"] = day.isoformat()
    await events.publish(
        session,
        EVENT,
        payload,
        location_id=None,
        actor_id=None,
        dedup_key=f"{EVENT}:{day.isoformat()}",
    )


class SummaryState:
    """Последняя обработанная дата (в памяти процесса воркера)."""

    last_date: date | None = None


async def run_once(session: AsyncSession, now: datetime | None = None) -> bool:
    """Одна проверка: публикует сводку, если время наступило и за сегодня её ещё не было."""
    local = (now or datetime.now(UTC)).astimezone(app_tz())
    today = local.date()
    if SummaryState.last_date == today:
        return False
    at = parse_summary_time(await get_setting(session, "daily_summary_time"))
    if at is None or local.time().replace(second=0, microsecond=0) < at:
        return False
    await publish_summary(session, today)
    SummaryState.last_date = today
    return True
