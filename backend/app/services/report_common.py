"""Общие функции модуля 10: округление, периоды, область точек, выражения «день по поясу точки»."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Location, Role, User
from app.models.appointment import Appointment
from app.models.catalog import WorkPost
from app.schemas.reports import Kpi

CENT = Decimal("0.01")
ZERO = Decimal(0)
MAX_PERIOD_DAYS = 366
MIN_YEAR, MAX_YEAR = 2000, 2100
BUSY_APPOINTMENTS = ("scheduled", "confirmed", "arrived")
NOT_OVERDUE = ("ready", "closed", "cancelled")
FINAL_STATUSES = ("closed", "cancelled")


# ---------------- числа ----------------


def q2(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, ROUND_HALF_UP)


def money_s(value: Decimal | int | str) -> str:
    return f"{q2(value):.2f}"


def int_s(value: int | Decimal) -> str:
    return str(int(value))


def dec(value: Any) -> Decimal:
    """Значение из БД (или None) -> Decimal."""
    return ZERO if value is None else Decimal(str(value))


def ratio_pct(num: Decimal, den: Decimal) -> Decimal | None:
    """num / den × 100 с округлением; деление на ноль даёт None."""
    if den == 0:
        return None
    return q2(num * 100 / den)


def pct_s(value: Decimal | None) -> str | None:
    return None if value is None else f"{q2(value):.2f}"


def pct_or_zero(value: Decimal | None) -> str:
    return f"{q2(value if value is not None else ZERO):.2f}"


def cap100(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return min(q2(value), Decimal(100))


def hours_from_minutes(minutes: Decimal | int) -> Decimal:
    return q2(Decimal(minutes) / 60)


# ---------------- Kpi ----------------


def kpi_money(value: Decimal, previous: Decimal) -> Kpi:
    delta = ratio_pct(value - previous, previous)
    return Kpi(kind="money", value=money_s(value), previous=money_s(previous), delta=pct_s(delta))


def kpi_count(value: int, previous: int) -> Kpi:
    delta = ratio_pct(Decimal(value - previous), Decimal(previous))
    return Kpi(kind="count", value=str(value), previous=str(previous), delta=pct_s(delta))


def kpi_percent(value: Decimal, previous: Decimal) -> Kpi:
    return Kpi(
        kind="percent",
        value=pct_or_zero(value),
        previous=pct_or_zero(previous),
        delta=pct_s(q2(value) - q2(previous)),
    )


# ---------------- время ----------------


def tz_of(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def app_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def today_app() -> date:
    return datetime.now(app_tz()).date()


def local_today(loc: Location) -> date:
    return datetime.now(tz_of(loc.timezone)).date()


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Границы суток `day` в поясе tz (aware)."""
    lo = datetime.combine(day, time.min, tzinfo=tz)
    hi = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return lo, hi


def month_bounds(month: date) -> tuple[date, date]:
    """Первый и последний день месяца."""
    first = month.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


def parse_month(value: str | None, *, field: str = "month", allow_future: bool = False) -> date:
    """`YYYY-MM` -> первое число месяца; будущий месяц -> 422."""
    current = today_app().replace(day=1)
    if value is None:
        return current
    try:
        if len(value) != 7 or value[4] != "-":
            raise ValueError
        year, mon = int(value[:4]), int(value[5:])
        month = date(year, mon, 1)
    except ValueError:
        raise AppError(422, "validation_error", {field: "invalid"}) from None
    if not MIN_YEAR <= month.year <= MAX_YEAR or (month > current and not allow_future):
        raise AppError(422, "validation_error", {field: "invalid"})
    return month


def check_year(value: date, field: str) -> None:
    if not MIN_YEAR <= value.year <= MAX_YEAR:
        raise AppError(422, "validation_error", {field: "invalid"})


@dataclass(frozen=True)
class Period:
    date_from: date
    date_to: date

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    @property
    def previous(self) -> "Period":
        prev_to = self.date_from - timedelta(days=1)
        return Period(prev_to - timedelta(days=self.days - 1), prev_to)

    @property
    def utc_bounds(self) -> tuple[datetime, datetime]:
        """Грубый фильтр по UTC (с запасом на пояса), чтобы работали индексы."""
        lo = datetime.combine(self.date_from - timedelta(days=1), time.min, tzinfo=UTC)
        hi = datetime.combine(self.date_to + timedelta(days=2), time.min, tzinfo=UTC)
        return lo, hi


def resolve_period(
    date_from: date | None,
    date_to: date | None,
    *,
    max_days: int = MAX_PERIOD_DAYS,
    to_field: str = "date_to",
    from_field: str = "date_from",
) -> Period:
    if date_from is not None:
        check_year(date_from, from_field)
    if date_to is not None:
        check_year(date_to, to_field)
    to = date_to or (max(today_app(), date_from) if date_from else today_app())
    frm = date_from or to.replace(day=1)
    if to < frm or (to - frm).days + 1 > max_days:
        raise AppError(422, "validation_error", {to_field: "invalid_range"})
    return Period(frm, to)


# ---------------- точки ----------------


async def resolve_locations(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    location_id: uuid.UUID | None,
) -> list[Location]:
    """Точки отчёта. Директор: все или одна; остальные: только разрешённые (иначе 404)."""
    if location_id is not None:
        loc = await session.get(Location, location_id)
        if loc is None or (actor.role != Role.director and loc.id not in allowed):
            raise AppError(404, "not_found")
        return [loc]
    stmt = select(Location).order_by(Location.name)
    if actor.role != Role.director:
        stmt = stmt.where(Location.id.in_(allowed))
    return list((await session.scalars(stmt)).all())


def loc_ids(locs: list[Location]) -> list[uuid.UUID]:
    return [loc.id for loc in locs]


# ---------------- SQL-выражения ----------------


def local_day(col: Any) -> Any:
    """Календарный день отметки времени в поясе точки (Location должен быть в запросе)."""
    return cast(func.timezone(Location.timezone, col), Date)


def in_period(col: Any, p: Period) -> list[Any]:
    lo, hi = p.utc_bounds
    day = local_day(col)
    return [col >= lo, col < hi, day >= p.date_from, day <= p.date_to]


# ---------------- загрузка постов ----------------


def work_minutes(loc: Location) -> int:
    return (
        loc.work_end.hour * 60
        + loc.work_end.minute
        - loc.work_start.hour * 60
        - loc.work_start.minute
    )


async def post_load(
    session: AsyncSession, locs: list[Location], p: Period
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """По точкам: (занятые минуты, доступные минуты) за период, ограниченный сегодняшним днём."""
    result: dict[uuid.UUID, tuple[Decimal, Decimal]] = {loc.id: (ZERO, ZERO) for loc in locs}
    if not locs:
        return result
    ids = loc_ids(locs)
    posts = {
        lid: n
        for lid, n in await session.execute(
            select(WorkPost.location_id, func.count())
            .where(WorkPost.location_id.in_(ids), WorkPost.is_active.is_(True))
            .group_by(WorkPost.location_id)
        )
    }
    today_local = cast(func.timezone(Location.timezone, func.now()), Date)
    lo, hi = p.utc_bounds
    occupied = {
        lid: dec(total)
        for lid, total in await session.execute(
            select(
                Appointment.location_id,
                func.sum(extract("epoch", Appointment.end_at - Appointment.start_at) / 60),
            )
            .join(Location, Location.id == Appointment.location_id)
            .where(
                Appointment.location_id.in_(ids),
                Appointment.status.in_(BUSY_APPOINTMENTS),
                Appointment.post_id.is_not(None),
                Appointment.start_at >= lo,
                Appointment.start_at < hi,
                local_day(Appointment.start_at) >= p.date_from,
                local_day(Appointment.start_at) <= func.least(p.date_to, today_local),
            )
            .group_by(Appointment.location_id)
        )
    }
    for loc in locs:
        eff_to = min(p.date_to, local_today(loc))
        days = max((eff_to - p.date_from).days + 1, 0)
        avail = Decimal(posts.get(loc.id, 0) * work_minutes(loc) * days)
        result[loc.id] = (min(occupied.get(loc.id, ZERO), avail), avail)
    return result


def load_percent(occupied: Decimal, available: Decimal) -> Decimal:
    return cap100(ratio_pct(occupied, available))
