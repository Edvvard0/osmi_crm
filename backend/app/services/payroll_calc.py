"""Расчёт зарплаты за месяц (модуль 10). Ведомость не хранится: считается по работам и схемам."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location, Role, User, UserLocation, Vehicle
from app.models.payroll import PayrollAdjustment, PayrollScheme
from app.models.work_order import WorkOrderItem
from app.services.report_common import ZERO, Period, dec, month_bounds, q2
from app.services.report_queries import closed_orders

DEPARTMENT_RU = {"service": "сервис", "detailing": "детейлинг"}


# ---------------- описание схем ----------------


def fmt_number(value: Decimal) -> str:
    """40.00 -> «40», 12.50 -> «12,5»."""
    text = f"{value.normalize():f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def fmt_rub(value: Decimal) -> str:
    quant = q2(value)
    whole, frac = divmod(quant, Decimal(1))
    text = f"{int(whole):,}".replace(",", " ")
    if frac:
        text += f",{int(frac * 100):02d}"
    return f"{text} ₽"


def describe_scheme(scheme: PayrollScheme, *, with_department: bool = True) -> str:
    kind = scheme.scheme_type
    if kind == "percent_of_works":
        text = f"{fmt_number(dec(scheme.percent))} % от работ"
    elif kind == "per_norm_hour":
        text = f"{fmt_rub(dec(scheme.norm_hour_rate))} за нормочас"
    elif kind == "fixed_plus_percent":
        text = f"{fmt_rub(dec(scheme.fixed_monthly))} в месяц + {fmt_number(dec(scheme.percent))} %"
    else:
        text = f"{fmt_rub(dec(scheme.fixed_monthly))} в месяц"
    if with_department and scheme.department:
        text += f" ({DEPARTMENT_RU[scheme.department]})"
    return text


# ---------------- структуры расчёта ----------------


@dataclass
class ItemLine:
    item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    location_id: uuid.UUID
    closed_at: datetime
    day: date
    name: str
    department: str
    quantity: Decimal
    norm_hours_total: Decimal
    actual_minutes: int
    finished_at: datetime | None
    plate_number: str | None
    item_net: Decimal
    scheme_id: uuid.UUID | None = None
    amount: Decimal = ZERO


@dataclass
class FixedLine:
    scheme_id: uuid.UUID
    days: int
    days_in_month: int
    amount: Decimal


@dataclass
class UserCalc:
    user: User
    items: list[ItemLine] = field(default_factory=list)
    fixed: list[FixedLine] = field(default_factory=list)
    adjustments: list[PayrollAdjustment] = field(default_factory=list)
    schemes: list[PayrollScheme] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)

    @property
    def items_done(self) -> int:
        return len(self.items)

    @property
    def norm_hours(self) -> Decimal:
        return q2(sum((i.norm_hours_total for i in self.items), ZERO))

    @property
    def actual_minutes(self) -> int:
        return sum(i.actual_minutes for i in self.items)

    @property
    def base_amount(self) -> Decimal:
        return sum((i.item_net for i in self.items), ZERO)

    @property
    def items_amount(self) -> Decimal:
        return sum((i.amount for i in self.items), ZERO)

    @property
    def fixed_amount(self) -> Decimal:
        return sum((f.amount for f in self.fixed), ZERO)

    @property
    def accrued(self) -> Decimal:
        return self.items_amount + self.fixed_amount

    @property
    def adjustments_total(self) -> Decimal:
        return sum((a.amount for a in self.adjustments), ZERO)

    @property
    def total(self) -> Decimal:
        return self.accrued + self.adjustments_total

    @property
    def items_without_scheme(self) -> int:
        return sum(1 for i in self.items if i.scheme_id is None)

    @property
    def scheme_summary(self) -> str:
        if not self.schemes:
            return "Схема не задана"
        return " · ".join(describe_scheme(s) for s in self.schemes)


# ---------------- расчёт ----------------


def _in_force(scheme: PayrollScheme, day: date) -> bool:
    return scheme.valid_from <= day and (scheme.valid_to is None or scheme.valid_to >= day)


def pick_scheme(schemes: list[PayrollScheme], day: date, department: str) -> PayrollScheme | None:
    """Схема отдела приоритетнее общей; нет ни одной -> None."""
    active = [s for s in schemes if _in_force(s, day)]
    for scheme in active:
        if scheme.department == department:
            return scheme
    for scheme in active:
        if scheme.department is None:
            return scheme
    return None


def item_amount(scheme: PayrollScheme, line: ItemLine) -> Decimal:
    if scheme.scheme_type in ("percent_of_works", "fixed_plus_percent"):
        return q2(line.item_net * dec(scheme.percent) / 100)
    if scheme.scheme_type == "per_norm_hour":
        return q2(line.norm_hours_total * dec(scheme.norm_hour_rate))
    return ZERO


def fixed_lines(schemes: list[PayrollScheme], first: date, last: date) -> list[FixedLine]:
    days_in_month = (last - first).days + 1
    lines: list[FixedLine] = []
    for scheme in schemes:
        if scheme.scheme_type not in ("fixed", "fixed_plus_percent") or scheme.department:
            continue
        lo = max(scheme.valid_from, first)
        hi = min(scheme.valid_to or last, last)
        days = (hi - lo).days + 1
        if days <= 0:
            continue
        amount = q2(dec(scheme.fixed_monthly) * days / days_in_month)
        lines.append(FixedLine(scheme.id, days, days_in_month, amount))
    return lines


async def _month_items(
    session: AsyncSession, first: date, last: date, location_id: uuid.UUID | None
) -> list[tuple[uuid.UUID, ItemLine]]:
    co = closed_orders(Period(first, last), [location_id] if location_id else None)
    rows = await session.execute(
        select(
            WorkOrderItem.id,
            WorkOrderItem.mechanic_id,
            co.c.id,
            co.c.number,
            co.c.location_id,
            co.c.closed_at,
            co.c.day,
            co.c.discount_percent,
            WorkOrderItem.name,
            WorkOrderItem.department,
            WorkOrderItem.quantity,
            WorkOrderItem.norm_hours,
            WorkOrderItem.total,
            WorkOrderItem.actual_minutes,
            WorkOrderItem.finished_at,
            Vehicle.plate_number,
        )
        .select_from(co)
        .join(WorkOrderItem, WorkOrderItem.work_order_id == co.c.id)
        .join(User, User.id == WorkOrderItem.mechanic_id)
        .outerjoin(Vehicle, Vehicle.id == co.c.vehicle_id)
        .where(WorkOrderItem.status == "done", User.role == Role.mechanic)
        .order_by(co.c.closed_at, WorkOrderItem.sort_order, WorkOrderItem.id)
    )
    lines: list[tuple[uuid.UUID, ItemLine]] = []
    for r in rows:
        net = q2(dec(r[12]) * (1 - dec(r[7]) / 100))
        lines.append(
            (
                r[1],
                ItemLine(
                    item_id=r[0],
                    order_id=r[2],
                    order_number=r[3],
                    location_id=r[4],
                    closed_at=r[5],
                    day=r[6],
                    name=r[8],
                    department=r[9],
                    quantity=dec(r[10]),
                    norm_hours_total=q2(dec(r[11]) * dec(r[10])),
                    actual_minutes=int(r[13] or 0),
                    finished_at=r[14],
                    plate_number=r[15],
                    item_net=net,
                ),
            )
        )
    return lines


async def calculate_month(
    session: AsyncSession,
    month: date,
    *,
    location_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, UserCalc]:
    """Расчёт за месяц. `user_id` — один сотрудник (всегда присутствует в ответе)."""
    first, last = month_bounds(month)

    raw_items = await _month_items(session, first, last, location_id)
    by_user_items: dict[uuid.UUID, list[ItemLine]] = {}
    for uid, line in raw_items:
        if user_id is None or uid == user_id:
            by_user_items.setdefault(uid, []).append(line)

    scheme_stmt = select(PayrollScheme).where(
        PayrollScheme.valid_from <= last,
        or_(PayrollScheme.valid_to.is_(None), PayrollScheme.valid_to >= first),
    )
    adj_stmt = select(PayrollAdjustment).where(PayrollAdjustment.period_month == first)
    if user_id is not None:
        scheme_stmt = scheme_stmt.where(PayrollScheme.user_id == user_id)
        adj_stmt = adj_stmt.where(PayrollAdjustment.user_id == user_id)
    elif location_id is not None:
        bound = select(UserLocation.user_id).where(UserLocation.location_id == location_id)
        scope = or_(
            PayrollScheme.user_id.in_(bound), PayrollScheme.user_id.in_(list(by_user_items))
        )
        scheme_stmt = scheme_stmt.where(scope)
        adj_stmt = adj_stmt.where(
            or_(
                PayrollAdjustment.user_id.in_(bound),
                PayrollAdjustment.user_id.in_(list(by_user_items)),
            )
        )
    schemes = list(
        await session.scalars(
            scheme_stmt.order_by(PayrollScheme.valid_from, PayrollScheme.department.nulls_first())
        )
    )
    adjustments = list(await session.scalars(adj_stmt.order_by(PayrollAdjustment.created_at)))

    user_ids: set[uuid.UUID] = set(by_user_items)
    user_ids.update(s.user_id for s in schemes)
    user_ids.update(a.user_id for a in adjustments)
    if user_id is not None:
        user_ids.add(user_id)
    if not user_ids:
        return {}

    users = {
        u.id: u
        for u in await session.scalars(
            select(User).where(User.id.in_(user_ids)).order_by(User.full_name, User.id)
        )
    }
    loc_rows = await session.execute(
        select(UserLocation.user_id, Location)
        .join(Location, Location.id == UserLocation.location_id)
        .where(UserLocation.user_id.in_(user_ids))
        .order_by(Location.name)
    )
    locations: dict[uuid.UUID, list[Location]] = {}
    for uid, loc in loc_rows:
        locations.setdefault(uid, []).append(loc)

    result: dict[uuid.UUID, UserCalc] = {}
    for uid, user in users.items():
        calc = UserCalc(user=user, locations=locations.get(uid, []))
        calc.schemes = [s for s in schemes if s.user_id == uid]
        calc.adjustments = [a for a in adjustments if a.user_id == uid]
        calc.items = by_user_items.get(uid, [])
        for line in calc.items:
            scheme = pick_scheme(calc.schemes, line.day, line.department)
            if scheme is not None:
                line.scheme_id = scheme.id
                line.amount = item_amount(scheme, line)
        calc.fixed = fixed_lines(calc.schemes, first, last)
        result[uid] = calc
    return result


def months_between(first: date, last: date) -> list[date]:
    months: list[date] = []
    cur = first.replace(day=1)
    while cur <= last:
        months.append(cur)
        cur = (cur + timedelta(days=32)).replace(day=1)
    return months


async def payroll_by_location(
    session: AsyncSession, date_from: date, date_to: date
) -> dict[uuid.UUID, Decimal]:
    """Начисленная зарплата по точкам за месяцы периода (для отчёта «Прибыль»).

    Позиции относятся к точке заказа; оклад и корректировки — к первой по имени точке сотрудника.
    """
    result: dict[uuid.UUID, Decimal] = {}
    for month in months_between(date_from, date_to):
        for calc in (await calculate_month(session, month)).values():
            for line in calc.items:
                result[line.location_id] = result.get(line.location_id, ZERO) + line.amount
            rest = calc.fixed_amount + calc.adjustments_total
            if rest and calc.locations:
                loc_id = calc.locations[0].id
                result[loc_id] = result.get(loc_id, ZERO) + rest
    return result
