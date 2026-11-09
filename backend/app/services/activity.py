"""Тепловая карта активности сотрудника и детализация дней (модуль 10, D-05 / MG-17 / M-07)."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Date, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import Location, Role, User, UserLocation, Vehicle
from app.models.audit import AuditLog
from app.models.cash import Payment
from app.models.mechanic import WorkLog
from app.models.work_order import (
    WorkOrder,
    WorkOrderComment,
    WorkOrderItem,
    WorkOrderPart,
)
from app.schemas.activity import (
    ActionEntry,
    ActivityDay,
    ActivityDetails,
    ActivityDetailsDay,
    ActivityHeatmap,
    ActivitySummary,
    HoursEntry,
)
from app.schemas.audit import UserRef
from app.schemas.payroll import PayrollOrderRef
from app.services.report_common import (
    ZERO,
    check_year,
    day_bounds,
    money_s,
    tz_of,
)
from app.services.settings import get_setting

MAX_HEATMAP_DAYS = 366
MAX_DETAIL_DAYS = 31
MAX_ENTRIES = 200
MAX_ORDER_NUMBERS = 10
EXCLUDED_ACTIONS = ("login", "login_failed", "logout", "token_reuse", "password_change")

ENTITY_RU = {
    "work_order": "заказ",
    "work_order_item": "работа",
    "work_order_part": "запчасть",
    "work_order_comment": "комментарий",
    "payment": "оплата",
    "client": "клиент",
    "vehicle": "автомобиль",
    "vehicle_recommendation": "рекомендация",
    "appointment": "запись",
    "expense": "расход",
    "expense_category": "категория расходов",
    "part_request": "запрос запчасти",
    "stock_movement": "движение склада",
    "stock_receipt": "приход на склад",
    "stock_transfer": "перемещение",
    "stock_inventory": "инвентаризация",
    "stock_balance": "остаток склада",
    "service_price": "цена услуги",
    "location": "точка",
    "user": "сотрудник",
    "session": "сеанс",
    "system_settings": "настройки",
    "payroll_scheme": "схема оплаты",
    "payroll_adjustment": "корректировка зарплаты",
    "report": "отчёт",
    "payroll": "ведомость",
}
ACTION_RU = {
    "create": "создание",
    "update": "изменение",
    "delete": "удаление",
    "archive": "архивирование",
    "restore": "восстановление",
    "status_change": "смена статуса",
    "refund": "возврат",
    "export": "экспорт",
    "revoke_session": "завершение сеанса",
}


# ---------------- доступ и параметры ----------------


@dataclass
class Target:
    user: User
    kind: str
    tz_name: str
    tz: ZoneInfo

    @property
    def today(self) -> date:
        return datetime.now(self.tz).date()


def kind_of(user: User) -> str:
    return "hours" if user.role == Role.mechanic else "actions"


async def resolve_target(
    session: AsyncSession, actor: User, allowed: list[uuid.UUID], user_id: uuid.UUID
) -> Target:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "not_found")
    if actor.role == Role.mechanic:
        if user.id != actor.id:
            raise AppError(404, "not_found")
    elif actor.role == Role.manager:
        if user.role != Role.mechanic or user.id == actor.id:
            raise AppError(404, "not_found")
        shared = await session.scalar(
            select(UserLocation.user_id)
            .where(UserLocation.user_id == user.id, UserLocation.location_id.in_(allowed))
            .limit(1)
        )
        if shared is None:
            raise AppError(404, "not_found")
    tz_name = await session.scalar(
        select(Location.timezone)
        .join(UserLocation, UserLocation.location_id == Location.id)
        .where(UserLocation.user_id == user.id)
        .order_by(Location.name)
        .limit(1)
    )
    tz_name = tz_name or get_settings().app_timezone
    return Target(user, kind_of(user), tz_name, tz_of(tz_name))


def _user_ref(user: User) -> UserRef:
    return UserRef(id=user.id, full_name=user.full_name)


# ---------------- интервалы механика ----------------


@dataclass
class Part:
    day: date
    seconds: float
    item_id: uuid.UUID
    item_name: str
    order_id: uuid.UUID
    order_number: str
    plate_number: str | None
    started_at: datetime
    ended_at: datetime | None


def _split(
    started: datetime, ended: datetime | None, now: datetime, tz: ZoneInfo
) -> list[tuple[date, float]]:
    """Делит интервал по местным полуночам. Пауза между интервалами не учитывается."""
    end = ended or now
    cur = started.astimezone(UTC)
    end = end.astimezone(UTC)
    result: list[tuple[date, float]] = []
    while cur < end:
        day = cur.astimezone(tz).date()
        nxt = day_bounds(day, tz)[1].astimezone(UTC)
        seg_end = min(end, nxt)
        if seg_end <= cur:
            break
        result.append((day, (seg_end - cur).total_seconds()))
        cur = seg_end
    return result


async def _hours_parts(
    session: AsyncSession, user_id: uuid.UUID, first: date, last: date
) -> list[Part]:
    lo = datetime.combine(first - timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    hi = datetime.combine(last + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    now = datetime.now(UTC)
    rows = await session.execute(
        select(
            WorkLog.item_id,
            WorkLog.started_at,
            WorkLog.ended_at,
            WorkOrderItem.name,
            WorkOrder.id,
            WorkOrder.number,
            Location.timezone,
            Vehicle.plate_number,
        )
        .join(WorkOrderItem, WorkOrderItem.id == WorkLog.item_id)
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .join(Location, Location.id == WorkOrder.location_id)
        .outerjoin(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
        .where(
            WorkLog.mechanic_id == user_id,
            WorkLog.started_at < hi,
            func.coalesce(WorkLog.ended_at, now) > lo,
        )
        .order_by(WorkLog.started_at)
    )
    parts: list[Part] = []
    for item_id, started, ended, item_name, order_id, number, tz_name, plate in rows:
        for day, seconds in _split(started, ended, now, tz_of(tz_name)):
            if first <= day <= last:
                parts.append(
                    Part(day, seconds, item_id, item_name, order_id, number, plate, started, ended)
                )
    return parts


def _minutes(seconds: float) -> int:
    return int(Decimal(seconds / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------- действия менеджера / директора ----------------


def _audit_day() -> ColumnElement[date]:
    tz = func.coalesce(Location.timezone, get_settings().app_timezone)
    return cast(func.timezone(tz, AuditLog.created_at), Date)


def _audit_filters(user_id: uuid.UUID, first: date, last: date) -> list[ColumnElement[bool]]:
    lo = datetime.combine(first - timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    hi = datetime.combine(last + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    day = _audit_day()
    return [
        AuditLog.user_id == user_id,
        AuditLog.action.not_in(EXCLUDED_ACTIONS),
        AuditLog.created_at >= lo,
        AuditLog.created_at < hi,
        day >= first,
        day <= last,
    ]


# ---------------- уровни ----------------


def _thresholds(raw: object, kind: str) -> list[int | float]:
    values = raw.get(kind) if isinstance(raw, dict) else None
    return list(values) if values else ([2, 5, 8] if kind == "hours" else [5, 15, 30])


def level_of(value: Decimal, thresholds: list[int | float]) -> int:
    if value <= 0:
        return 0
    for i, t in enumerate(thresholds[:3], start=1):
        if value <= Decimal(str(t)):
            return i
    return 4


# ---------------- тепловая карта ----------------


def _heatmap_period(
    target: Target, date_from: date | None, date_to: date | None
) -> tuple[date, date]:
    if date_from is not None:
        check_year(date_from, "from")
    if date_to is not None:
        check_year(date_to, "to")
    to = date_to or target.today
    frm = date_from or to - timedelta(days=364)
    if to < frm or (to - frm).days + 1 > MAX_HEATMAP_DAYS:
        raise AppError(422, "validation_error", {"to": "invalid_range"})
    return frm, to


async def heatmap(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    user_id: uuid.UUID,
    date_from: date | None,
    date_to: date | None,
) -> ActivityHeatmap:
    target = await resolve_target(session, actor, allowed, user_id)
    frm, to = _heatmap_period(target, date_from, date_to)
    last = min(to, target.today)
    thresholds = _thresholds(await get_setting(session, "heatmap_thresholds"), target.kind)

    # значение дня (секунды или действия), число работ, номера заказов
    values: dict[date, float] = {}
    works: dict[date, int] = {}
    orders: dict[date, list[str]] = {}
    if last >= frm:
        if target.kind == "hours":
            values, works, orders = await _hours_by_day(session, target, frm, last)
        else:
            values, works, orders = await _actions_by_day(session, target, frm, last)

    days: list[ActivityDay] = []
    total = ZERO
    working = streak = longest = 0
    day = frm
    while day <= last:
        raw = values.get(day, 0)
        if target.kind == "hours":
            hours_exact = Decimal(raw) / 3600
            level = level_of(hours_exact, thresholds)
            minutes = _minutes(raw) if raw else 0
            days.append(
                ActivityDay(
                    date=day,
                    minutes=minutes,
                    hours=money_s(hours_exact),
                    actions=None,
                    works_count=works.get(day, 0),
                    level=level,
                    order_numbers=orders.get(day, []),
                )
            )
            total += hours_exact
        else:
            count = int(raw)
            level = level_of(Decimal(count), thresholds)
            days.append(
                ActivityDay(
                    date=day,
                    minutes=None,
                    hours=None,
                    actions=count,
                    works_count=works.get(day, 0),
                    level=level,
                    order_numbers=orders.get(day, []),
                )
            )
            total += Decimal(count)
        if level >= 1:
            working += 1
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
        day += timedelta(days=1)

    if target.kind == "hours":
        average = (
            (total / working).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if working
            else Decimal("0.00")
        )
        average_s = f"{average:.2f}"
        summary = ActivitySummary(
            working_days=working,
            total_hours=money_s(total),
            total_actions=None,
            average_per_working_day=average_s,
            longest_streak_days=longest,
        )
    else:
        average = (
            (total / working).quantize(Decimal("0.1"), ROUND_HALF_UP) if working else Decimal("0.0")
        )
        summary = ActivitySummary(
            working_days=working,
            total_hours=None,
            total_actions=int(total),
            average_per_working_day=f"{average:.1f}",
            longest_streak_days=longest,
        )
    return ActivityHeatmap(
        user=_user_ref(target.user),
        kind=target.kind,
        from_=frm,
        to=to,
        timezone=target.tz_name,
        first_day=target.user.created_at.astimezone(target.tz).date(),
        thresholds=thresholds,
        days=days,
        summary=summary,
    )


def _top_numbers(per_order: dict[str, float]) -> list[str]:
    ranked = sorted(per_order.items(), key=lambda kv: (-kv[1], kv[0]))
    return [number for number, _ in ranked[:MAX_ORDER_NUMBERS]]


async def _hours_by_day(
    session: AsyncSession, target: Target, first: date, last: date
) -> tuple[dict[date, float], dict[date, int], dict[date, list[str]]]:
    seconds: dict[date, float] = defaultdict(float)
    items: dict[date, set[uuid.UUID]] = defaultdict(set)
    per_order: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for part in await _hours_parts(session, target.user.id, first, last):
        seconds[part.day] += part.seconds
        items[part.day].add(part.item_id)
        per_order[part.day][part.order_number] += part.seconds
    return (
        dict(seconds),
        {d: len(s) for d, s in items.items()},
        {d: _top_numbers(o) for d, o in per_order.items()},
    )


async def _actions_by_day(
    session: AsyncSession, target: Target, first: date, last: date
) -> tuple[dict[date, float], dict[date, int], dict[date, list[str]]]:
    day = _audit_day()
    filters = _audit_filters(target.user.id, first, last)
    counts: dict[date, float] = {}
    works: dict[date, int] = {}
    stmt = (
        select(
            day,
            func.count(),
            func.count(func.distinct(AuditLog.entity_id)).filter(
                AuditLog.entity_type == "work_order"
            ),
        )
        .select_from(AuditLog)
        .outerjoin(Location, Location.id == AuditLog.location_id)
        .where(*filters)
        .group_by(day)
    )
    for d, n, w in await session.execute(stmt):
        counts[d] = float(n)
        works[d] = int(w)
    per_day: dict[date, dict[uuid.UUID, int]] = defaultdict(dict)
    rows = await session.execute(
        select(day, AuditLog.entity_id, func.count())
        .select_from(AuditLog)
        .outerjoin(Location, Location.id == AuditLog.location_id)
        .where(*filters, AuditLog.entity_type == "work_order", AuditLog.entity_id.is_not(None))
        .group_by(day, AuditLog.entity_id)
    )
    order_ids: set[uuid.UUID] = set()
    for d, entity_id, n in rows:
        assert entity_id is not None  # отфильтровано в запросе (is_not(None))
        per_day[d][entity_id] = int(n)
        order_ids.add(entity_id)
    numbers: dict[uuid.UUID, str] = {}
    if order_ids:
        numbers = dict(
            (
                await session.execute(
                    select(WorkOrder.id, WorkOrder.number).where(WorkOrder.id.in_(order_ids))
                )
            ).all()
        )
    orders: dict[date, list[str]] = {}
    for d, per in per_day.items():
        ranked: defaultdict[str, float] = defaultdict(float)
        for oid, n in per.items():
            if oid in numbers:
                ranked[numbers[oid]] += n
        orders[d] = _top_numbers(ranked)
    return counts, works, orders


# ---------------- детализация ----------------


async def _order_numbers_for(
    session: AsyncSession, rows: list[tuple[str, uuid.UUID | None]]
) -> dict[tuple[str, uuid.UUID], str]:
    """Номера заказов для записей аудита, связанных с заказом."""
    by_type: dict[str, set[uuid.UUID]] = defaultdict(set)
    for entity_type, entity_id in rows:
        if entity_id is not None:
            by_type[entity_type].add(entity_id)
    result: dict[tuple[str, uuid.UUID], str] = {}

    async def fill(entity_type: str, model: type, fk: object | None) -> None:
        ids = by_type.get(entity_type)
        if not ids:
            return
        if fk is None:
            stmt = select(WorkOrder.id, WorkOrder.number).where(WorkOrder.id.in_(ids))
        else:
            stmt = (
                select(model.id, WorkOrder.number)  # type: ignore[attr-defined]
                .join(WorkOrder, WorkOrder.id == fk)
                .where(model.id.in_(ids))  # type: ignore[attr-defined]
            )
        for eid, number in await session.execute(stmt):
            result[(entity_type, eid)] = number

    await fill("work_order", WorkOrder, None)
    await fill("work_order_item", WorkOrderItem, WorkOrderItem.work_order_id)
    await fill("work_order_part", WorkOrderPart, WorkOrderPart.work_order_id)
    await fill("work_order_comment", WorkOrderComment, WorkOrderComment.work_order_id)
    await fill("payment", Payment, Payment.work_order_id)
    return result


def _label(action: str, entity_type: str, order_number: str | None) -> str:
    act = ACTION_RU.get(action, action)
    entity = ENTITY_RU.get(entity_type, entity_type)
    if entity_type == "work_order" and order_number:
        return f"Заказ {order_number}: {act}"
    if order_number:
        return f"Заказ {order_number}: {entity} — {act}"
    return f"{entity[:1].upper()}{entity[1:]}: {act}"


async def details(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    user_id: uuid.UUID,
    date_from: date | None,
    date_to: date | None,
) -> ActivityDetails:
    target = await resolve_target(session, actor, allowed, user_id)
    if date_from is not None:
        check_year(date_from, "date_from")
    if date_to is not None:
        check_year(date_to, "date_to")
    to = date_to or date_from or target.today
    frm = date_from or to
    if to < frm or (to - frm).days + 1 > MAX_DETAIL_DAYS:
        raise AppError(422, "validation_error", {"date_to": "invalid_range"})
    if target.kind == "hours":
        days = await _hours_details(session, target, frm, to)
    else:
        days = await _action_details(session, target, frm, to)
    return ActivityDetails(
        user=_user_ref(target.user),
        kind=target.kind,
        days=days,
    )


async def _hours_details(
    session: AsyncSession, target: Target, first: date, last: date
) -> list[ActivityDetailsDay]:
    by_day: dict[date, list[Part]] = defaultdict(list)
    for part in await _hours_parts(session, target.user.id, first, last):
        by_day[part.day].append(part)
    result: list[ActivityDetailsDay] = []
    for day in sorted(by_day, reverse=True):
        parts = sorted(by_day[day], key=lambda x: (x.started_at, x.item_id))
        total = sum(x.seconds for x in parts)
        result.append(
            ActivityDetailsDay(
                date=day,
                total_minutes=_minutes(total),
                actions=None,
                truncated=len(parts) > MAX_ENTRIES,
                entries=[
                    HoursEntry(
                        order=PayrollOrderRef(id=x.order_id, number=x.order_number),
                        plate_number=x.plate_number,
                        item_id=x.item_id,
                        item_name=x.item_name,
                        started_at=x.started_at,
                        ended_at=x.ended_at,
                        minutes=_minutes(x.seconds),
                    )
                    for x in parts[:MAX_ENTRIES]
                ],
            )
        )
    return result


async def _action_details(
    session: AsyncSession, target: Target, first: date, last: date
) -> list[ActivityDetailsDay]:
    day = _audit_day()
    filters = _audit_filters(target.user.id, first, last)
    totals: dict[date, int] = {
        d: int(n)
        for d, n in await session.execute(
            select(day, func.count())
            .select_from(AuditLog)
            .outerjoin(Location, Location.id == AuditLog.location_id)
            .where(*filters)
            .group_by(day)
        )
    }
    ranked = (
        select(
            AuditLog.created_at.label("at"),
            AuditLog.action.label("action"),
            AuditLog.entity_type.label("entity_type"),
            AuditLog.entity_id.label("entity_id"),
            day.label("d"),
            func.row_number()
            .over(partition_by=day, order_by=(AuditLog.created_at, AuditLog.id))
            .label("rn"),
        )
        .select_from(AuditLog)
        .outerjoin(Location, Location.id == AuditLog.location_id)
        .where(*filters)
        .subquery("ranked")
    )
    rows = (
        await session.execute(
            select(ranked)
            .where(and_(ranked.c.rn <= MAX_ENTRIES))
            .order_by(ranked.c.d.desc(), ranked.c.at, ranked.c.rn)
        )
    ).all()
    numbers = await _order_numbers_for(session, [(r.entity_type, r.entity_id) for r in rows])
    entries: dict[date, list[ActionEntry]] = defaultdict(list)
    for r in rows:
        number = numbers.get((r.entity_type, r.entity_id)) if r.entity_id else None
        entries[r.d].append(
            ActionEntry(
                at=r.at,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                label=_label(r.action, r.entity_type, number),
                order_number=number,
            )
        )
    return [
        ActivityDetailsDay(
            date=d,
            total_minutes=None,
            actions=totals[d],
            truncated=totals[d] > MAX_ENTRIES,
            entries=entries.get(d, []),
        )
        for d in sorted(totals, reverse=True)
    ]
