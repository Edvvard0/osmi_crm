"""Заказ-наряды (модуль 5): создание, шапка, работы, запчасти, статусы, комментарии, выборки."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.errors import AppError
from app.core.ids import new_id
from app.core.types import _LAT2CYR
from app.models import (
    Client,
    Location,
    Part,
    Role,
    Service,
    ServiceLocationPrice,
    User,
    UserLocation,
    Vehicle,
)
from app.models.appointment import Appointment, AppointmentService
from app.models.mechanic import PartRequest
from app.models.work_order import (
    LocationCounter,
    WorkOrder,
    WorkOrderComment,
    WorkOrderItem,
    WorkOrderPart,
    WorkOrderStatusHistory,
)
from app.schemas.appointment import ClientRef, VehicleRef
from app.schemas.work_order import (
    BoardColumn,
    ClientFull,
    CommentAuthor,
    CommentCreate,
    ItemCreate,
    ItemUpdate,
    NewItem,
    OrderBoard,
    OrderSummary,
    PartCreate,
    PartUpdate,
    StatusChangeBody,
    StatusHistoryEntry,
    UserRef,
    VehicleFull,
    WorkOrderCommentRead,
    WorkOrderCreate,
    WorkOrderItemRead,
    WorkOrderListItem,
    WorkOrderPage,
    WorkOrderPartRead,
    WorkOrderRead,
    WorkOrderUpdate,
)
from app.services import events, stock_service, timers
from app.services.audit import ClientInfo, diff, write_audit
from app.services.payment_status import recalc_payment_status, refunded_total
from app.services.settings import get_setting

LIFECYCLE = (
    "new",
    "diagnostics",
    "awaiting_approval",
    "in_progress",
    "awaiting_parts",
    "quality_check",
    "ready",
    "closed",
    "cancelled",
)
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("diagnostics", "in_progress", "cancelled"),
    "diagnostics": ("awaiting_approval", "in_progress", "cancelled"),
    "awaiting_approval": ("diagnostics", "in_progress", "cancelled"),
    "in_progress": ("awaiting_parts", "quality_check", "cancelled"),
    "awaiting_parts": ("in_progress", "cancelled"),
    "quality_check": ("in_progress", "ready", "cancelled"),
    "ready": ("in_progress", "closed", "cancelled"),
    "closed": (),
    "cancelled": (),
}
FINAL = frozenset({"closed", "cancelled"})
NOT_OVERDUE = ("ready", "closed", "cancelled")
NEEDS_ITEMS = frozenset({"in_progress", "quality_check", "ready", "closed"})
VEHICLE_CHANGE_STATUSES = frozenset({"new", "diagnostics", "awaiting_approval"})
ITEM_OPEN = frozenset({"pending", "in_progress", "paused"})
STATUSES_SET = frozenset(LIFECYCLE)
BOARD_LIMIT = 100
MAX_RANGE_DAYS = 366
_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_ZERO = Decimal("0.00")
_SORTS = frozenset({"created_at", "planned_ready_at", "number", "total", "status"})


# ---------------- вычисления ----------------


def q2(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def item_total(quantity: Decimal, unit_price: Decimal, discount: Decimal) -> Decimal:
    return q2(quantity * unit_price * (_HUNDRED - discount) / _HUNDRED)


def part_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return q2(quantity * unit_price)


def computed_department(items: list[WorkOrderItem], current: str) -> str:
    kinds = {i.department for i in items if i.status != "cancelled"}
    if not kinds:
        return current
    return next(iter(kinds)) if len(kinds) == 1 else "mixed"


def max_discount(order: WorkOrder, items: list[WorkOrderItem]) -> Decimal:
    values = [order.discount_percent]
    values += [i.discount_percent for i in items if i.status != "cancelled"]
    return max(values)


def _unprocessable(**fields: str) -> AppError:
    return AppError(422, "validation_error", dict(fields))


def _tz(loc: Location) -> ZoneInfo:
    return ZoneInfo(loc.timezone)


def _iso(dt: datetime | None, tz: ZoneInfo | None = None) -> str | None:
    if dt is None:
        return None
    return (dt.astimezone(tz) if tz else dt).isoformat()


# ---------------- доступ и загрузка ----------------


async def _get_location(
    session: AsyncSession, location_id: uuid.UUID, allowed: list[uuid.UUID]
) -> Location:
    if location_id not in allowed:
        raise AppError(404, "not_found")
    loc = await session.get(Location, location_id)
    if loc is None:  # pragma: no cover - allowed строится из существующих точек
        raise AppError(404, "not_found")
    return loc


async def _get_order(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> WorkOrder:
    if for_update:
        order = await session.get(WorkOrder, order_id, with_for_update=True, populate_existing=True)
    else:
        order = await session.get(WorkOrder, order_id)
    if order is None or order.location_id not in allowed:
        raise AppError(404, "not_found")
    return order


def _check_version(order: WorkOrder, version: int) -> None:
    if order.version != version:
        raise AppError(409, "version_conflict", details={"current_version": str(order.version)})


def _check_open(order: WorkOrder) -> None:
    if order.status in FINAL:
        raise AppError(409, "invalid_state")


async def _items_of(session: AsyncSession, order_id: uuid.UUID) -> list[WorkOrderItem]:
    rows = await session.scalars(
        select(WorkOrderItem)
        .where(WorkOrderItem.work_order_id == order_id)
        .order_by(WorkOrderItem.sort_order, WorkOrderItem.created_at, WorkOrderItem.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _parts_of(session: AsyncSession, order_id: uuid.UUID) -> list[WorkOrderPart]:
    rows = await session.scalars(
        select(WorkOrderPart)
        .where(WorkOrderPart.work_order_id == order_id)
        .order_by(WorkOrderPart.created_at, WorkOrderPart.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _find_item(session: AsyncSession, order: WorkOrder, item_id: uuid.UUID) -> WorkOrderItem:
    item = await session.get(WorkOrderItem, item_id, populate_existing=True)
    if item is None or item.work_order_id != order.id:
        raise AppError(404, "not_found")
    return item


async def _find_part(
    session: AsyncSession, order: WorkOrder, row_id: uuid.UUID
) -> WorkOrderPart:
    row = await session.get(WorkOrderPart, row_id, populate_existing=True)
    if row is None or row.work_order_id != order.id:
        raise AppError(404, "not_found")
    return row


# ---------------- чтение ----------------


@dataclass
class _Ctx:
    clients: dict[uuid.UUID, Client]
    vehicles: dict[uuid.UUID, Vehicle]
    users: dict[uuid.UUID, User]
    zones: dict[uuid.UUID, ZoneInfo]
    stats: dict[uuid.UUID, tuple[int, int, list[uuid.UUID]]]


def _ref(user: User) -> UserRef:
    return UserRef(id=user.id, full_name=user.full_name)


async def _load_ctx(session: AsyncSession, orders: list[WorkOrder]) -> _Ctx:
    if not orders:
        return _Ctx({}, {}, {}, {}, {})
    ids = [o.id for o in orders]
    clients = {
        c.id: c
        for c in await session.scalars(
            select(Client).where(Client.id.in_({o.client_id for o in orders}))
        )
    }
    vehicles = {
        v.id: v
        for v in await session.scalars(
            select(Vehicle).where(Vehicle.id.in_({o.vehicle_id for o in orders}))
        )
    }
    zones = {
        loc.id: _tz(loc)
        for loc in await session.scalars(
            select(Location).where(Location.id.in_({o.location_id for o in orders}))
        )
    }
    counts: dict[uuid.UUID, list[Any]] = {i: [0, 0, []] for i in ids}
    user_ids = {o.manager_id for o in orders}
    for oid, status, mid in await session.execute(
        select(WorkOrderItem.work_order_id, WorkOrderItem.status, WorkOrderItem.mechanic_id).where(
            WorkOrderItem.work_order_id.in_(ids)
        )
    ):
        if status == "cancelled":
            continue
        row = counts[oid]
        row[0] += 1
        row[1] += 1 if status == "done" else 0
        if mid is not None and mid not in row[2]:
            row[2].append(mid)
            user_ids.add(mid)
    users = {u.id: u for u in await session.scalars(select(User).where(User.id.in_(user_ids)))}
    stats = {k: (v[0], v[1], v[2]) for k, v in counts.items()}
    return _Ctx(clients, vehicles, users, zones, stats)


def _row(o: WorkOrder, ctx: _Ctx, now: datetime) -> dict[str, Any]:
    tz = ctx.zones[o.location_id]
    count, done, mech_ids = ctx.stats[o.id]
    mechanics = sorted((ctx.users[m] for m in mech_ids), key=lambda u: (u.full_name, str(u.id)))
    overdue = (
        o.planned_ready_at is not None
        and o.planned_ready_at < now
        and o.status not in NOT_OVERDUE
    )
    return {
        "id": o.id,
        "number": o.number,
        "location_id": o.location_id,
        "status": o.status,
        "department": o.department,
        "created_at": o.created_at.astimezone(tz),
        "planned_ready_at": o.planned_ready_at.astimezone(tz) if o.planned_ready_at else None,
        "is_overdue": overdue,
        "mileage_in": o.mileage_in,
        "manager": _ref(ctx.users[o.manager_id]),
        "mechanics": [_ref(u) for u in mechanics],
        "items_count": count,
        "items_done_count": done,
        "works_total": o.works_total,
        "parts_total": o.parts_total,
        "discount_total": o.discount_total,
        "total": o.total,
        "paid_total": o.paid_total,
        "balance_due": max(o.total - o.paid_total, _ZERO),
        "payment_status": o.payment_status,
        "version": o.version,
    }


def _client_ref(c: Client) -> ClientRef:
    return ClientRef(id=c.id, full_name=c.full_name, phone=c.phone)


def _vehicle_ref(v: Vehicle) -> VehicleRef:
    return VehicleRef(id=v.id, make=v.make, model=v.model, plate_number=v.plate_number)


async def _list_reads(session: AsyncSession, orders: list[WorkOrder]) -> list[WorkOrderListItem]:
    ctx = await _load_ctx(session, orders)
    now = datetime.now(UTC)
    return [
        WorkOrderListItem(
            **_row(o, ctx, now),
            client=_client_ref(ctx.clients[o.client_id]),
            vehicle=_vehicle_ref(ctx.vehicles[o.vehicle_id]),
        )
        for o in orders
    ]


async def _detail(session: AsyncSession, order: WorkOrder) -> WorkOrderRead:
    await session.refresh(order)
    ctx = await _load_ctx(session, [order])
    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    extra_ids = {i.mechanic_id for i in items if i.mechanic_id} | {p.added_by for p in parts}
    users = dict(ctx.users)
    missing = extra_ids - users.keys()
    if missing:
        found = await session.scalars(select(User).where(User.id.in_(missing)))
        users.update({u.id: u for u in found})
    tz = ctx.zones[order.location_id]
    stock = await stock_service.stock_for_parts(
        session,
        location_id=order.location_id,
        part_ids={p.part_id for p in parts if p.part_id is not None},
    )
    appointment_id = await session.scalar(
        select(Appointment.id).where(Appointment.work_order_id == order.id)
    )
    client, vehicle = ctx.clients[order.client_id], ctx.vehicles[order.vehicle_id]

    def local(dt: datetime | None) -> datetime | None:
        return dt.astimezone(tz) if dt else None

    def local_req(dt: datetime) -> datetime:
        return dt.astimezone(tz)

    return WorkOrderRead(
        **_row(order, ctx, datetime.now(UTC)),
        refunded_total=await refunded_total(session, order.id),
        client=ClientFull(
            id=client.id,
            full_name=client.full_name,
            phone=client.phone,
            discount_percent=float(client.discount_percent),
        ),
        vehicle=VehicleFull(
            id=vehicle.id,
            make=vehicle.make,
            model=vehicle.model,
            plate_number=vehicle.plate_number,
            year=vehicle.year,
            vin=vehicle.vin,
            color=vehicle.color,
            mileage=vehicle.mileage,
        ),
        complaint=order.complaint,
        intake_notes=order.intake_notes,
        diagnosis=order.diagnosis,
        discount_percent=order.discount_percent,
        started_at=local(order.started_at),
        ready_at=local(order.ready_at),
        closed_at=local(order.closed_at),
        cancel_reason=order.cancel_reason,
        appointment_id=appointment_id,
        items=[
            WorkOrderItemRead(
                id=i.id,
                service_id=i.service_id,
                name=i.name,
                department=i.department,
                quantity=i.quantity,
                unit_price=i.unit_price,
                discount_percent=i.discount_percent,
                total=i.total,
                norm_hours=i.norm_hours,
                norm_hours_total=q2(i.norm_hours * i.quantity),
                mechanic=_ref(users[i.mechanic_id]) if i.mechanic_id else None,
                status=i.status,
                started_at=local(i.started_at),
                finished_at=local(i.finished_at),
                actual_minutes=i.actual_minutes,
                sort_order=i.sort_order,
            )
            for i in items
        ],
        parts=[
            WorkOrderPartRead(
                id=p.id,
                part_id=p.part_id,
                name=p.name,
                sku=p.sku,
                unit=p.unit,
                quantity=p.quantity,
                unit_price=p.unit_price,
                total=p.total,
                unit_cost=p.unit_cost,
                in_stock=stock.get(p.part_id) if p.part_id is not None else None,
                added_by=_ref(users[p.added_by]),
                created_at=local_req(p.created_at),
            )
            for p in parts
        ],
        allowed_transitions=list(TRANSITIONS[order.status]),
        updated_at=local_req(order.updated_at),
    )


def _hide_cost(read: WorkOrderRead, actor: User) -> WorkOrderRead:
    """`unit_cost` (себестоимость) видит только руководитель."""
    if actor.role != Role.director:
        for p in read.parts:
            p.unit_cost = None
    return read


async def get_order(
    session: AsyncSession, actor: User, allowed: list[uuid.UUID], order_id: uuid.UUID
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id)
    return _hide_cost(await _detail(session, order), actor)


async def _respond(session: AsyncSession, actor: User, order: WorkOrder) -> WorkOrderRead:
    return _hide_cost(await _detail(session, order), actor)


# ---------------- списки ----------------


def _scope(location_id: uuid.UUID | None, allowed: list[uuid.UUID]) -> list[uuid.UUID]:
    if location_id is not None:
        if location_id not in allowed:
            raise AppError(404, "not_found")
        return [location_id]
    return list(allowed)


def _board_scope(
    actor: User, allowed: list[uuid.UUID], location_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Доска и счётчики: менеджер с несколькими точками обязан указать `location_id`."""
    if location_id is None and actor.role != Role.director and len(allowed) > 1:
        raise _unprocessable(location_id="required")
    return _scope(location_id, allowed)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _overdue_clause(now: datetime) -> Any:
    return and_(WorkOrder.planned_ready_at < now, WorkOrder.status.notin_(NOT_OVERDUE))


def _search_clause(search: str) -> Any:
    text_ = search.strip()
    pat = f"%{_escape_like(text_)}%"
    plate = f"%{_escape_like(re.sub(r'\s', '', text_).upper().translate(_LAT2CYR))}%"
    conds = [
        WorkOrder.number.ilike(pat, escape="\\"),
        Vehicle.plate_number.ilike(plate, escape="\\"),
        Vehicle.vin.ilike(pat, escape="\\"),
        Client.full_name.ilike(pat, escape="\\"),
        Client.company_name.ilike(pat, escape="\\"),
    ]
    digits = re.sub(r"\D", "", text_)
    if len(digits) >= 3:
        conds.append(Client.phone.like(f"%{digits}"))
    return or_(*conds)


async def _date_clause(
    session: AsyncSession,
    scope: list[uuid.UUID],
    date_from: date | None,
    date_to: date | None,
) -> Any:
    if date_from is None and date_to is None:
        return None
    if (
        date_from is not None
        and date_to is not None
        and (date_to < date_from or (date_to - date_from).days >= MAX_RANGE_DAYS)
    ):
        raise _unprocessable(date_to="invalid")
    locs = list(await session.scalars(select(Location).where(Location.id.in_(scope))))
    parts = []
    for loc in locs:
        tz = _tz(loc)
        conds = [WorkOrder.location_id == loc.id]
        if date_from is not None:
            conds.append(WorkOrder.created_at >= datetime.combine(date_from, time.min, tzinfo=tz))
        if date_to is not None:
            conds.append(
                WorkOrder.created_at
                < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
            )
        parts.append(and_(*conds))
    return or_(*parts) if parts else WorkOrder.id.is_(None)


def _base_select(*cols: Any) -> Select[Any]:
    return (
        select(*cols)
        .select_from(WorkOrder)
        .join(Client, Client.id == WorkOrder.client_id)
        .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
    )


def _mechanic_clause(mechanic_id: uuid.UUID) -> Any:
    return exists().where(
        WorkOrderItem.work_order_id == WorkOrder.id,
        WorkOrderItem.mechanic_id == mechanic_id,
        WorkOrderItem.status != "cancelled",
    )


async def list_orders(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID | None = None,
    status: str | None = None,
    department: str | None = None,
    manager_id: uuid.UUID | None = None,
    mechanic_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    payment_status: str | None = None,
    overdue: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> WorkOrderPage:
    scope = _scope(location_id, allowed)
    conds: list[Any] = [WorkOrder.location_id.in_(scope)]
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        if not wanted or any(s not in STATUSES_SET for s in wanted):
            raise _unprocessable(status="invalid")
        conds.append(WorkOrder.status.in_(wanted))
    if department:
        conds.append(WorkOrder.department == department)
    if manager_id:
        conds.append(WorkOrder.manager_id == manager_id)
    if mechanic_id:
        conds.append(_mechanic_clause(mechanic_id))
    if client_id:
        conds.append(WorkOrder.client_id == client_id)
    if vehicle_id:
        conds.append(WorkOrder.vehicle_id == vehicle_id)
    if payment_status:
        conds.append(WorkOrder.payment_status == payment_status)
    if overdue:
        conds.append(_overdue_clause(datetime.now(UTC)))
    dates = await _date_clause(session, scope, date_from, date_to)
    if dates is not None:
        conds.append(dates)
    if search and search.strip():
        conds.append(_search_clause(search))

    if sort not in _SORTS:
        raise _unprocessable(sort="invalid")
    if sort == "status":
        key: Any = case({s: i for i, s in enumerate(LIFECYCLE)}, value=WorkOrder.status)
    else:
        key = getattr(WorkOrder, sort)
    direction = key.asc() if order == "asc" else key.desc()
    if sort == "planned_ready_at":
        direction = direction.nulls_last()

    total = await session.scalar(_base_select(func.count(WorkOrder.id)).where(*conds)) or 0
    rows = await session.scalars(
        _base_select(WorkOrder)
        .where(*conds)
        .order_by(direction, WorkOrder.id.desc() if order != "asc" else WorkOrder.id)
        .limit(limit)
        .offset(offset)
    )
    return WorkOrderPage(items=await _list_reads(session, list(rows)), total=total)


async def board(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID | None = None,
    department: str | None = None,
    manager_id: uuid.UUID | None = None,
    mechanic_id: uuid.UUID | None = None,
    overdue: bool | None = None,
) -> OrderBoard:
    scope = _board_scope(actor, allowed, location_id)
    now = datetime.now(UTC)
    conds: list[Any] = [WorkOrder.location_id.in_(scope)]
    if department:
        conds.append(WorkOrder.department == department)
    if manager_id:
        conds.append(WorkOrder.manager_id == manager_id)
    if mechanic_id:
        conds.append(_mechanic_clause(mechanic_id))
    if overdue:
        conds.append(_overdue_clause(now))
    columns: list[tuple[str, int, list[WorkOrder]]] = []
    for status in LIFECYCLE[:-1]:
        col = [*conds, WorkOrder.status == status]
        if status == "closed":
            col.append(WorkOrder.closed_at >= now - timedelta(days=7))
        total = await session.scalar(select(func.count(WorkOrder.id)).where(*col)) or 0
        rows = await session.scalars(
            select(WorkOrder)
            .where(*col)
            .order_by(
                WorkOrder.planned_ready_at.asc().nulls_last(), WorkOrder.created_at, WorkOrder.id
            )
            .limit(BOARD_LIMIT)
        )
        columns.append((status, total, list(rows)))
    flat = [o for _, _, rows in columns for o in rows]
    reads = {r.id: r for r in await _list_reads(session, flat)}
    return OrderBoard(
        columns=[
            BoardColumn(status=s, total=t, items=[reads[o.id] for o in rows])
            for s, t, rows in columns
        ]
    )


async def summary(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    location_id: uuid.UUID | None = None,
) -> OrderSummary:
    scope = _board_scope(actor, allowed, location_id)
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(
                func.count().filter(WorkOrder.status == "in_progress"),
                func.count().filter(WorkOrder.status == "awaiting_parts"),
                func.count().filter(WorkOrder.status == "ready"),
                func.count().filter(_overdue_clause(now)),
                func.count().filter(WorkOrder.status.notin_(tuple(FINAL))),
            ).where(WorkOrder.location_id.in_(scope))
        )
    ).one()
    return OrderSummary(
        in_progress=row[0],
        awaiting_parts=row[1],
        ready=row[2],
        overdue=row[3],
        open_total=row[4],
    )


async def history_of_subject(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    client_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> WorkOrderPage:
    """История заказов клиента/авто: менеджеру — только его точки (и `total` тоже)."""
    if client_id is not None and await session.get(Client, client_id) is None:
        raise AppError(404, "not_found")
    if vehicle_id is not None and await session.get(Vehicle, vehicle_id) is None:
        raise AppError(404, "not_found")
    return await list_orders(
        session,
        allowed,
        client_id=client_id,
        vehicle_id=vehicle_id,
        status=status,
        limit=limit,
        offset=offset,
    )


async def status_history(
    session: AsyncSession, allowed: list[uuid.UUID], order_id: uuid.UUID
) -> list[StatusHistoryEntry]:
    order = await _get_order(session, allowed, order_id)
    rows = list(
        await session.scalars(
            select(WorkOrderStatusHistory)
            .where(WorkOrderStatusHistory.work_order_id == order.id)
            .order_by(WorkOrderStatusHistory.created_at, WorkOrderStatusHistory.id)
        )
    )
    users = {
        u.id: u
        for u in await session.scalars(
            select(User).where(User.id.in_({r.changed_by for r in rows}))
        )
    }
    loc = await session.get(Location, order.location_id)
    tz = _tz(loc) if loc else ZoneInfo("UTC")
    return [
        StatusHistoryEntry(
            id=r.id,
            from_status=r.from_status,
            to_status=r.to_status,
            changed_by=_ref(users[r.changed_by]),
            comment=r.comment,
            created_at=r.created_at.astimezone(tz),
        )
        for r in rows
    ]


# ---------------- общие шаги записи ----------------


async def _next_number(session: AsyncSession, loc: Location) -> str:
    await session.execute(
        pg_insert(LocationCounter)
        .values(location_id=loc.id, counter_type="work_order", last_value=0)
        .on_conflict_do_nothing()
    )
    value = await session.scalar(
        update(LocationCounter)
        .where(LocationCounter.location_id == loc.id, LocationCounter.counter_type == "work_order")
        .values(last_value=LocationCounter.last_value + 1)
        .returning(LocationCounter.last_value)
    )
    return f"{loc.code}-{value:06d}"


async def _recalc(
    session: AsyncSession,
    order: WorkOrder,
    items: list[WorkOrderItem],
    parts: list[WorkOrderPart],
) -> None:
    """Пересчёт строк и итогов заказа; при смене `total` — хук модуля 9."""
    old_total = order.total
    for i in items:
        i.total = item_total(i.quantity, i.unit_price, i.discount_percent)
    for p in parts:
        p.total = part_total(p.quantity, p.unit_price)
    works = sum((i.total for i in items if i.status != "cancelled"), _ZERO)
    parts_sum = sum((p.total for p in parts), _ZERO)
    discount = q2((works + parts_sum) * order.discount_percent / _HUNDRED)
    order.works_total, order.parts_total, order.discount_total = works, parts_sum, discount
    order.total = works + parts_sum - discount
    order.department = computed_department(items, order.department)
    if order.total != old_total:
        await recalc_payment_status(session, order)


async def _save(
    session: AsyncSession,
    actor: User,
    order: WorkOrder,
    items: list[WorkOrderItem],
    parts: list[WorkOrderPart],
    *,
    old_max_discount: Decimal,
    old_version: int | None = None,
) -> None:
    """Пересчёт, +1 к версии, событие о скидке; коммит делает вызывающий после аудита."""
    await _recalc(session, order, items, parts)
    order.version = (old_version if old_version is not None else order.version) + 1
    await session.flush()
    new_max = max_discount(order, items)
    if new_max > old_max_discount and new_max > Decimal(
        str(await get_setting(session, "discount_alert_percent"))
    ):
        loc = await session.get(Location, order.location_id)
        await events.publish(
            session,
            "order.discount_alert",
            {
                "order_id": str(order.id),
                "order_number": order.number,
                "discount_percent": f"{new_max:.2f}",
                "location_name": loc.name if loc else None,
                "user_name": actor.full_name,
            },
            location_id=order.location_id,
            actor_id=actor.id,
            dedup_key=f"order.discount_alert:{order.id}:{new_max:.2f}",
        )


def _audit(
    session: AsyncSession,
    actor: User,
    client_info: ClientInfo,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    order: WorkOrder,
    changes: dict[str, Any] | None,
) -> None:
    if entity_type != "work_order":
        changes = {**(changes or {}), "work_order_id": {"old": None, "new": str(order.id)}}
    write_audit(
        session,
        action=action,
        entity_type=entity_type,
        user_id=actor.id,
        entity_id=entity_id,
        location_id=order.location_id,
        changes=changes,
        client=client_info,
    )


def _order_snapshot(o: WorkOrder) -> dict[str, Any]:
    return {
        "mileage_in": o.mileage_in,
        "complaint": o.complaint,
        "intake_notes": o.intake_notes,
        "diagnosis": o.diagnosis,
        "planned_ready_at": (
            _iso(o.planned_ready_at.astimezone(UTC)) if o.planned_ready_at else None
        ),
        "discount_percent": f"{o.discount_percent:.2f}",
        "manager_id": str(o.manager_id),
        "vehicle_id": str(o.vehicle_id),
    }


def _item_snapshot(i: WorkOrderItem) -> dict[str, Any]:
    return {
        "name": i.name,
        "service_id": str(i.service_id) if i.service_id else None,
        "department": i.department,
        "quantity": f"{i.quantity:.2f}",
        "unit_price": f"{i.unit_price:.2f}",
        "discount_percent": f"{i.discount_percent:.2f}",
        "norm_hours": f"{i.norm_hours:.2f}",
        "mechanic_id": str(i.mechanic_id) if i.mechanic_id else None,
        "status": i.status,
        "sort_order": i.sort_order,
    }


def _part_snapshot(p: WorkOrderPart) -> dict[str, Any]:
    return {
        "part_id": str(p.part_id) if p.part_id else None,
        "name": p.name,
        "quantity": f"{p.quantity:.3f}",
        "unit_price": f"{p.unit_price:.2f}",
    }


def _created(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {k: {"old": None, "new": v} for k, v in snapshot.items()}


async def _history(
    session: AsyncSession,
    order: WorkOrder,
    from_status: str | None,
    to_status: str,
    user_id: uuid.UUID,
    comment: str | None,
) -> None:
    session.add(
        WorkOrderStatusHistory(
            work_order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            changed_by=user_id,
            comment=comment,
        )
    )


# ---------------- проверки ссылок ----------------


async def _check_mechanic(
    session: AsyncSession, mechanic_id: uuid.UUID, location_id: uuid.UUID, field: str
) -> User:
    user = await session.get(User, mechanic_id)
    bound = user is not None and await session.scalar(
        select(UserLocation.user_id).where(
            UserLocation.user_id == mechanic_id, UserLocation.location_id == location_id
        )
    )
    if user is None or user.role != Role.mechanic or not user.is_active or not bound:
        raise _unprocessable(**{field: "invalid"})
    return user


async def _check_manager(
    session: AsyncSession, manager_id: uuid.UUID, location_id: uuid.UUID
) -> User:
    user = await session.get(User, manager_id)
    if user is None or not user.is_active or user.role not in (Role.manager, Role.director):
        raise _unprocessable(manager_id="invalid")
    if user.role != Role.director and not await session.scalar(
        select(UserLocation.user_id).where(
            UserLocation.user_id == manager_id, UserLocation.location_id == location_id
        )
    ):
        raise _unprocessable(manager_id="invalid")
    return user


async def _effective_price(
    session: AsyncSession, service: Service, location_id: uuid.UUID
) -> Decimal:
    price = await session.scalar(
        select(ServiceLocationPrice.price).where(
            ServiceLocationPrice.service_id == service.id,
            ServiceLocationPrice.location_id == location_id,
        )
    )
    return Decimal(price if price is not None else service.base_price)


async def _publish_assigned(
    session: AsyncSession, actor: User, order: WorkOrder, item: WorkOrderItem
) -> None:
    if item.mechanic_id is None:
        return
    vehicle = await session.get(Vehicle, order.vehicle_id)
    loc = await session.get(Location, order.location_id)
    tz = _tz(loc) if loc else None
    await events.publish(
        session,
        "work_item.assigned",
        {
            "order_id": str(order.id),
            "order_number": order.number,
            "item_id": str(item.id),
            "item_name": item.name,
            "make": vehicle.make if vehicle else None,
            "model": vehicle.model if vehicle else None,
            "plate_number": vehicle.plate_number if vehicle else None,
            "planned_ready_at": _iso(order.planned_ready_at, tz),
        },
        location_id=order.location_id,
        actor_id=actor.id,
        target_user_id=item.mechanic_id,
    )


async def _publish_item_updated(
    session: AsyncSession,
    actor: User,
    order: WorkOrder,
    item: WorkOrderItem,
    change: str,
) -> None:
    if item.mechanic_id is None:
        return
    loc = await session.get(Location, order.location_id)
    await events.publish(
        session,
        "work_item.updated",
        {
            "order_id": str(order.id),
            "order_number": order.number,
            "item_id": str(item.id),
            "item_name": item.name,
            "change": change,
            "planned_ready_at": _iso(order.planned_ready_at, _tz(loc) if loc else None),
        },
        location_id=order.location_id,
        actor_id=actor.id,
        target_user_id=item.mechanic_id,
    )


async def _build_item(
    session: AsyncSession,
    actor: User,
    location_id: uuid.UUID,
    new: NewItem,
    *,
    sort_order: int,
    prefix: str = "",
) -> WorkOrderItem:
    def key(name: str) -> str:
        return f"{prefix}{name}"

    if new.service_id is not None:
        errors = {
            key(n): "not_allowed"
            for n in ("name", "department", "norm_hours")
            if getattr(new, n) is not None
        }
        service = await session.get(Service, new.service_id)
        if service is None or not service.is_active:
            errors[key("service_id")] = "invalid"
        if errors:
            raise AppError(422, "validation_error", errors)
        assert service is not None
        catalog_price = await _effective_price(session, service, location_id)
        unit_price = catalog_price
        if new.unit_price is not None and new.unit_price != catalog_price:
            if actor.role != Role.director:
                raise AppError(403, "forbidden")
            unit_price = new.unit_price
        name, department, norm = service.name, service.department, Decimal(service.norm_hours)
        service_id: uuid.UUID | None = service.id
    else:
        errors = {
            key(n): "required"
            for n in ("name", "department", "unit_price")
            if getattr(new, n) is None
        }
        if errors:
            raise AppError(422, "validation_error", errors)
        assert new.name is not None and new.department is not None and new.unit_price is not None
        name, department, unit_price = new.name, new.department, new.unit_price
        norm = new.norm_hours if new.norm_hours is not None else _ZERO
        service_id = None
    if new.mechanic_id is not None:
        await _check_mechanic(session, new.mechanic_id, location_id, key("mechanic_id"))
    return WorkOrderItem(
        id=new_id(),
        service_id=service_id,
        name=name,
        department=department,
        quantity=new.quantity,
        unit_price=unit_price,
        discount_percent=new.discount_percent,
        total=item_total(new.quantity, unit_price, new.discount_percent),
        norm_hours=norm,
        mechanic_id=new.mechanic_id,
        status="pending",
        sort_order=sort_order,
    )


# ---------------- создание ----------------


async def _insert_order(
    session: AsyncSession,
    actor: User,
    loc: Location,
    *,
    client: Client,
    vehicle: Vehicle,
    department: str,
    manager_id: uuid.UUID,
    mileage_in: int | None,
    complaint: str | None,
    intake_notes: str | None,
    planned_ready_at: datetime | None,
    discount: Decimal,
    items: list[WorkOrderItem],
    appointment: Appointment | None,
    client_info: ClientInfo,
) -> WorkOrder:
    order = WorkOrder(
        id=new_id(),
        number=await _next_number(session, loc),
        location_id=loc.id,
        client_id=client.id,
        vehicle_id=vehicle.id,
        department=department,
        status="new",
        manager_id=manager_id,
        mileage_in=mileage_in,
        complaint=complaint,
        intake_notes=intake_notes,
        planned_ready_at=planned_ready_at,
        discount_percent=discount,
        works_total=_ZERO,
        parts_total=_ZERO,
        discount_total=_ZERO,
        total=_ZERO,
        paid_total=_ZERO,
        payment_status="unpaid",
        version=1,
    )
    session.add(order)
    await session.flush()
    for n, item in enumerate(items):
        item.work_order_id = order.id
        item.sort_order = n
        session.add(item)
    await session.flush()
    # Новый заказ: хук оплаты не нужен, пока итог нулевой.
    order.department = computed_department(items, order.department)
    works = sum((i.total for i in items), _ZERO)
    order.works_total = works
    order.discount_total = q2(works * discount / _HUNDRED)
    order.total = works - order.discount_total
    if order.total != _ZERO:
        await recalc_payment_status(session, order)
    await _history(session, order, None, "new", actor.id, None)

    if mileage_in is not None and (vehicle.mileage is None or mileage_in > vehicle.mileage):
        old_mileage = vehicle.mileage
        vehicle.mileage = mileage_in
        write_audit(
            session,
            action="update",
            entity_type="vehicle",
            user_id=actor.id,
            entity_id=vehicle.id,
            changes={"mileage": {"old": old_mileage, "new": mileage_in}},
            client=client_info,
        )
    if appointment is not None:
        old_status = appointment.status
        appointment.work_order_id = order.id
        appointment.status = "arrived"
        write_audit(
            session,
            action="update",
            entity_type="appointment",
            user_id=actor.id,
            entity_id=appointment.id,
            location_id=appointment.location_id,
            changes={
                "work_order_id": {"old": None, "new": str(order.id)},
                **(
                    {"status": {"old": old_status, "new": "arrived"}}
                    if old_status != "arrived"
                    else {}
                ),
            },
            client=client_info,
        )
    await session.flush()
    snapshot = {
        "number": order.number,
        "client_id": str(order.client_id),
        "vehicle_id": str(order.vehicle_id),
        "department": order.department,
        "status": order.status,
        **_order_snapshot(order),
    }
    write_audit(
        session,
        action="create",
        entity_type="work_order",
        user_id=actor.id,
        entity_id=order.id,
        location_id=order.location_id,
        changes=_created(snapshot),
        client=client_info,
    )
    for item in items:
        _audit(
            session,
            actor,
            client_info,
            action="create",
            entity_type="work_order_item",
            entity_id=item.id,
            order=order,
            changes=_created(_item_snapshot(item)),
        )
        await _publish_assigned(session, actor, order, item)
    new_max = max_discount(order, items)
    if new_max > Decimal(str(await get_setting(session, "discount_alert_percent"))):
        await events.publish(
            session,
            "order.discount_alert",
            {
                "order_id": str(order.id),
                "order_number": order.number,
                "discount_percent": f"{new_max:.2f}",
                "location_name": loc.name,
                "user_name": actor.full_name,
            },
            location_id=order.location_id,
            actor_id=actor.id,
            dedup_key=f"order.discount_alert:{order.id}:{new_max:.2f}",
        )
    return order


async def create_order(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    data: WorkOrderCreate,
    client_info: ClientInfo,
) -> WorkOrderRead:
    loc = await _get_location(session, data.location_id, allowed)
    now = datetime.now(UTC)

    appointment: Appointment | None = None
    client_id, vehicle_id = data.client_id, data.vehicle_id
    department = data.department
    if data.appointment_id is not None:
        appointment = await session.get(
            Appointment, data.appointment_id, with_for_update=True, populate_existing=True
        )
        if appointment is None or appointment.location_id not in allowed:
            raise AppError(404, "not_found")
        if appointment.work_order_id is not None:
            existing = await session.get(WorkOrder, appointment.work_order_id)
            raise AppError(
                409,
                "appointment_has_order",
                details={
                    "work_order_id": str(appointment.work_order_id),
                    "work_order_number": existing.number if existing else "",
                },
            )
        if appointment.status not in ("scheduled", "confirmed", "arrived"):
            raise AppError(409, "invalid_state")
        if (
            appointment.location_id != loc.id
            or (client_id is not None and client_id != appointment.client_id)
            or (vehicle_id is not None and vehicle_id != appointment.vehicle_id)
        ):
            raise _unprocessable(appointment_id="invalid")
        client_id, vehicle_id = appointment.client_id, appointment.vehicle_id
        department = appointment.department  # type: ignore[assignment]

    if client_id is None:
        raise _unprocessable(client_id="required")
    client = await session.get(Client, client_id)
    if client is None or client.archived_at is not None:
        raise _unprocessable(client_id="invalid")
    if vehicle_id is None:
        raise _unprocessable(vehicle_id="required")
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.archived_at is not None or vehicle.client_id != client.id:
        raise _unprocessable(vehicle_id="invalid")

    manager_id = actor.id
    if data.manager_id is not None and data.manager_id != actor.id:
        manager_id = (await _check_manager(session, data.manager_id, loc.id)).id
    elif actor.role != Role.director:
        await _check_manager(session, actor.id, loc.id)
    if data.planned_ready_at is not None and data.planned_ready_at < now - timedelta(minutes=5):
        raise _unprocessable(planned_ready_at="invalid")

    items: list[WorkOrderItem] = []
    if data.items is not None:
        for n, spec in enumerate(data.items):
            items.append(
                await _build_item(
                    session, actor, loc.id, spec, sort_order=n, prefix=f"items.{n}."
                )
            )
    elif appointment is not None:
        service_ids = list(
            await session.scalars(
                select(AppointmentService.service_id)
                .join(Service, Service.id == AppointmentService.service_id)
                .where(AppointmentService.appointment_id == appointment.id)
                .order_by(Service.name, Service.id)
            )
        )
        for n, sid in enumerate(service_ids):
            items.append(
                await _build_item(session, actor, loc.id, NewItem(service_id=sid), sort_order=n)
            )

    discount = (
        data.discount_percent
        if data.discount_percent is not None
        else Decimal(client.discount_percent).quantize(_CENT, rounding=ROUND_HALF_UP)
    )
    order = await _insert_order(
        session,
        actor,
        loc,
        client=client,
        vehicle=vehicle,
        department=department or "service",
        manager_id=manager_id,
        mileage_in=data.mileage_in,
        complaint=data.complaint or None,
        intake_notes=data.intake_notes or None,
        planned_ready_at=data.planned_ready_at,
        discount=discount,
        items=items,
        appointment=appointment,
        client_info=client_info,
    )
    await session.commit()
    return await _respond(session, actor, order)


async def duplicate_order(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    client_info: ClientInfo,
) -> WorkOrderRead:
    src = await _get_order(session, allowed, order_id)
    loc = await _get_location(session, src.location_id, allowed)
    client = await session.get(Client, src.client_id)
    vehicle = await session.get(Vehicle, src.vehicle_id)
    if client is None or vehicle is None:  # pragma: no cover - FK
        raise AppError(404, "not_found")
    if client.archived_at is not None:
        raise _unprocessable(client_id="invalid")
    if vehicle.archived_at is not None:
        raise _unprocessable(vehicle_id="invalid")
    items: list[WorkOrderItem] = []
    for n, old in enumerate(i for i in await _items_of(session, src.id) if i.status != "cancelled"):
        price = old.unit_price
        if old.service_id is not None:
            service = await session.get(Service, old.service_id)
            if service is not None:
                price = await _effective_price(session, service, loc.id)
        items.append(
            WorkOrderItem(
                id=new_id(),
                service_id=old.service_id,
                name=old.name,
                department=old.department,
                quantity=old.quantity,
                unit_price=price,
                discount_percent=old.discount_percent,
                total=item_total(old.quantity, price, old.discount_percent),
                norm_hours=old.norm_hours,
                mechanic_id=None,
                status="pending",
                sort_order=n,
            )
        )
    order = await _insert_order(
        session,
        actor,
        loc,
        client=client,
        vehicle=vehicle,
        department=src.department,
        manager_id=actor.id,
        mileage_in=None,
        complaint=src.complaint,
        intake_notes=None,
        planned_ready_at=None,
        discount=src.discount_percent,
        items=items,
        appointment=None,
        client_info=client_info,
    )
    await session.commit()
    return await _respond(session, actor, order)


# ---------------- шапка ----------------


async def update_order(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    data: WorkOrderUpdate,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, data.version)
    _check_open(order)
    values = data.model_dump(exclude_unset=True)
    values.pop("version")
    if not values:
        return await _respond(session, actor, order)

    if "vehicle_id" in values:
        if order.status not in VEHICLE_CHANGE_STATUSES:
            raise AppError(409, "invalid_state")
        vehicle = await session.get(Vehicle, values["vehicle_id"])
        if (
            vehicle is None
            or vehicle.archived_at is not None
            or vehicle.client_id != order.client_id
        ):
            raise _unprocessable(vehicle_id="invalid")
    if "manager_id" in values:
        await _check_manager(session, values["manager_id"], order.location_id)

    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max, old_version = max_discount(order, items), order.version
    old = _order_snapshot(order)
    old_planned = order.planned_ready_at
    for name in ("mileage_in", "complaint", "intake_notes", "diagnosis", "planned_ready_at"):
        if name in values:
            setattr(order, name, values[name] or None if name != "mileage_in" else values[name])
    for name in ("discount_percent", "manager_id", "vehicle_id"):
        if name in values:
            setattr(order, name, values[name])
    changes = diff(old, _order_snapshot(order))
    if not changes:
        return await _respond(session, actor, order)
    await _save(
        session, actor, order, items, parts, old_max_discount=old_max, old_version=old_version
    )
    if order.planned_ready_at != old_planned:
        for item in items:
            if item.status in ITEM_OPEN and item.mechanic_id is not None:
                await _publish_item_updated(session, actor, order, item, "deadline")
    _audit(
        session,
        actor,
        client_info,
        action="update",
        entity_type="work_order",
        entity_id=order.id,
        order=order,
        changes=changes,
    )
    await session.commit()
    return await _respond(session, actor, order)


# ---------------- статусы ----------------


async def _apply_transition(
    session: AsyncSession,
    actor_id: uuid.UUID,
    order: WorkOrder,
    items: list[WorkOrderItem],
    parts: list[WorkOrderPart],
    to: str,
    *,
    comment: str | None,
    cancel_reason: str | None = None,
) -> str:
    """Побочные эффекты перехода (без проверок). Возвращает прежний статус."""
    now = datetime.now(UTC)
    old = order.status
    order.status = to
    if to in ("diagnostics", "in_progress") and order.started_at is None:
        order.started_at = now
    if to == "ready":
        order.ready_at = now
    if to == "closed":
        order.closed_at = now
    if to == "cancelled":
        order.cancel_reason = cancel_reason
        for item in items:
            if item.status != "cancelled":
                await timers.close_open_log(session, item)
                item.status = "cancelled"
        for row in sorted(parts, key=lambda p: str(p.part_id)):
            if row.stock_movement_id is not None:
                await stock_service.return_for_order(
                    session, order=order, part_row=row, actor_id=actor_id
                )
    elif to not in ("diagnostics", "in_progress"):
        await timers.pause_all(session, order)
        for item in items:
            if item.status == "in_progress":
                item.status = "paused"
    await _history(session, order, old, to, actor_id, comment)
    return old


async def change_status(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    data: StatusChangeBody,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, data.version)
    to = data.status
    if to not in TRANSITIONS[order.status]:
        raise AppError(409, "invalid_transition")
    items = await _items_of(session, order.id)
    active = [i for i in items if i.status != "cancelled"]
    if to in NEEDS_ITEMS and not active:
        raise AppError(409, "order_empty")
    if to == "ready":
        pending = sum(1 for i in active if i.status != "done")
        if pending:
            raise AppError(409, "items_not_done", details={"pending_count": str(pending)})
    if to == "cancelled" and not data.cancel_reason:
        raise _unprocessable(cancel_reason="required")
    # модуль 9: оплата
    forced_due: Decimal | None = None
    if data.force_close and to != "closed":
        raise _unprocessable(force_close="invalid")
    if to == "cancelled" and order.paid_total > _ZERO:
        raise AppError(409, "has_payments")
    if to == "closed":
        balance_due = max(order.total - order.paid_total, _ZERO)
        if balance_due > _ZERO:
            if not data.force_close:
                raise AppError(409, "order_not_paid", details={"balance_due": str(balance_due)})
            if actor.role != Role.director:
                raise AppError(403, "forbidden")
            if not data.comment:
                raise _unprocessable(comment="required")
            forced_due = balance_due
    parts = await _parts_of(session, order.id)
    old_version = order.version
    old = await _apply_transition(
        session,
        actor.id,
        order,
        items,
        parts,
        to,
        comment=(
            # comment в истории — String(500), а data.comment сам может быть до 500 символов
            f"Закрыт без полной оплаты (долг {forced_due}). {data.comment}"[:500]
            if forced_due is not None
            else data.comment or (data.cancel_reason if to == "cancelled" else None)
        ),
        cancel_reason=data.cancel_reason,
    )
    await _save(
        session,
        actor,
        order,
        items,
        parts,
        old_max_discount=max_discount(order, items),
        old_version=old_version,
    )
    write_audit(
        session,
        action="status_change",
        entity_type="work_order",
        user_id=actor.id,
        entity_id=order.id,
        location_id=order.location_id,
        changes={
            "status": {"old": old, "new": to},
            **(
                {"cancel_reason": {"old": None, "new": data.cancel_reason}}
                if to == "cancelled"
                else {}
            ),
            **({"forced": True, "balance_due": str(forced_due)} if forced_due is not None else {}),
        },
        client=client_info,
    )
    await session.commit()
    return await _respond(session, actor, order)


async def on_item_done(
    session: AsyncSession,
    order: WorkOrder,
    *,
    actor_id: uuid.UUID,
    client_info: ClientInfo | None = None,
) -> bool:
    """Вызывается после завершения работы (менеджером или механиком, модуль 6).

    Если все неотменённые работы выполнены, а заказ в `in_progress` — автопереход в
    `quality_check` с записью в историю и аудит. Версию заказа увеличивает вызывающий.
    """
    if order.status != "in_progress":
        return False
    items = await _items_of(session, order.id)
    active = [i for i in items if i.status != "cancelled"]
    if not active or any(i.status != "done" for i in active):
        return False
    parts = await _parts_of(session, order.id)
    old = await _apply_transition(
        session, actor_id, order, items, parts, "quality_check", comment="Все работы выполнены"
    )
    write_audit(
        session,
        action="status_change",
        entity_type="work_order",
        user_id=actor_id,
        entity_id=order.id,
        location_id=order.location_id,
        changes={"status": {"old": old, "new": "quality_check"}},
        client=client_info,
    )
    return True


# ---------------- работы ----------------


async def add_item(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    data: ItemCreate,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, data.version)
    _check_open(order)
    if order.status == "ready":
        raise AppError(409, "invalid_state")
    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max = max_discount(order, items)
    spec: NewItem = data  # ItemCreate — подкласс NewItem
    item = await _build_item(
        session,
        actor,
        order.location_id,
        spec,
        sort_order=max((i.sort_order for i in items), default=-1) + 1,
    )
    item.work_order_id = order.id
    session.add(item)
    items.append(item)
    await session.flush()
    await _save(session, actor, order, items, parts, old_max_discount=old_max)
    _audit(
        session,
        actor,
        client_info,
        action="create",
        entity_type="work_order_item",
        entity_id=item.id,
        order=order,
        changes=_created(_item_snapshot(item)),
    )
    await _publish_assigned(session, actor, order, item)
    await session.commit()
    return await _respond(session, actor, order)


_LOCKED_ITEM_FIELDS = ("quantity", "unit_price", "name", "norm_hours", "discount_percent")


async def update_item(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ItemUpdate,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, data.version)
    _check_open(order)
    item = await _find_item(session, order, item_id)
    values = data.model_dump(exclude_unset=True)
    values.pop("version")
    if not values:
        return await _respond(session, actor, order)

    locked = [f for f in _LOCKED_ITEM_FIELDS if f in values]
    if locked and item.status != "pending":
        raise AppError(409, "item_started")
    if item.service_id is not None:
        bad: dict[str, str] = {f: "not_allowed" for f in ("name", "norm_hours") if f in values}
        if bad:
            raise AppError(422, "validation_error", bad)
        if (
            "unit_price" in values
            and values["unit_price"] != item.unit_price
            and actor.role != Role.director
        ):
            raise AppError(403, "forbidden")
    old_mechanic = item.mechanic_id
    if "mechanic_id" in values and values["mechanic_id"] != old_mechanic:
        if item.status in ("done", "cancelled"):
            raise AppError(409, "invalid_state")
        if await timers.has_open_log(session, item):
            raise AppError(409, "item_active")
        if values["mechanic_id"] is not None:
            await _check_mechanic(session, values["mechanic_id"], order.location_id, "mechanic_id")

    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max, old_version = max_discount(order, items), order.version
    old = _item_snapshot(item)
    for name, value in values.items():
        setattr(item, name, value)
    changes = diff(old, _item_snapshot(item))
    if not changes:
        return await _respond(session, actor, order)
    await _save(
        session, actor, order, items, parts, old_max_discount=old_max, old_version=old_version
    )
    _audit(
        session,
        actor,
        client_info,
        action="update",
        entity_type="work_order_item",
        entity_id=item.id,
        order=order,
        changes=changes,
    )
    if item.mechanic_id is not None and item.mechanic_id != old_mechanic:
        await _publish_assigned(session, actor, order, item)
    await session.commit()
    return await _respond(session, actor, order)


async def delete_item(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    version: int,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, version)
    _check_open(order)
    item = await _find_item(session, order, item_id)
    has_comments = await session.scalar(
        select(exists().where(WorkOrderComment.item_id == item.id))
    )
    if (
        item.status != "pending"
        or item.started_at is not None
        or item.actual_minutes
        or has_comments
        or await timers.has_open_log(session, item)
    ):
        raise AppError(409, "item_started")
    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max = max_discount(order, items)
    snapshot = _item_snapshot(item)
    await session.execute(delete(WorkOrderItem).where(WorkOrderItem.id == item.id))
    session.expunge(item)
    items = [i for i in items if i.id != item.id]
    await _save(session, actor, order, items, parts, old_max_discount=old_max)
    _audit(
        session,
        actor,
        client_info,
        action="delete",
        entity_type="work_order_item",
        entity_id=item.id,
        order=order,
        changes={k: {"old": v, "new": None} for k, v in snapshot.items()},
    )
    await session.commit()
    return await _respond(session, actor, order)


async def cancel_item(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    version: int,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, version)
    _check_open(order)
    item = await _find_item(session, order, item_id)
    if item.status not in ITEM_OPEN:
        raise AppError(409, "invalid_state")
    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max, old_version = max_discount(order, items), order.version
    await timers.close_open_log(session, item)
    old_status, item.status = item.status, "cancelled"
    await _save(
        session, actor, order, items, parts, old_max_discount=old_max, old_version=old_version
    )
    _audit(
        session,
        actor,
        client_info,
        action="status_change",
        entity_type="work_order_item",
        entity_id=item.id,
        order=order,
        changes={"status": {"old": old_status, "new": "cancelled"}},
    )
    await session.commit()
    return await _respond(session, actor, order)


async def complete_item(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    version: int,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, version)
    _check_open(order)
    item = await _find_item(session, order, item_id)
    if item.status not in ITEM_OPEN:
        raise AppError(409, "invalid_state")
    if item.mechanic_id is None:
        raise _unprocessable(mechanic_id="required")
    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max, old_version = max_discount(order, items), order.version
    now = datetime.now(UTC)
    await timers.close_open_log(session, item)
    old_status, item.status = item.status, "done"
    item.finished_at = now
    if item.started_at is None:
        item.started_at = now
    await session.flush()
    await on_item_done(session, order, actor_id=actor.id, client_info=client_info)
    await _save(
        session, actor, order, items, parts, old_max_discount=old_max, old_version=old_version
    )
    _audit(
        session,
        actor,
        client_info,
        action="status_change",
        entity_type="work_order_item",
        entity_id=item.id,
        order=order,
        changes={"status": {"old": old_status, "new": "done"}},
    )
    await session.commit()
    return await _respond(session, actor, order)


# ---------------- запчасти ----------------


async def add_part(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    data: PartCreate,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, data.version)
    _check_open(order)
    if data.part_id is not None:
        if data.name is not None:
            raise _unprocessable(name="not_allowed")
        part = await session.get(Part, data.part_id)
        if part is None or not part.is_active:
            raise _unprocessable(part_id="invalid")
        unit_price = Decimal(part.sale_price)
        if data.unit_price is not None and data.unit_price != unit_price:
            if actor.role != Role.director:
                raise AppError(403, "forbidden")
            unit_price = data.unit_price
        name, sku, unit = part.name, part.sku, part.unit
    else:
        missing = {
            k: "required" for k in ("name", "unit_price") if getattr(data, k) is None
        }
        if missing:
            raise AppError(422, "validation_error", missing)
        assert data.name is not None and data.unit_price is not None
        name, sku, unit, unit_price = data.name, None, None, data.unit_price
        part = None
    request = None
    if data.part_request_id is not None:
        # FOR UPDATE: approve/reject заявки (part_requests.py) блокируют только саму заявку
        request = await session.get(
            PartRequest, data.part_request_id, with_for_update=True, populate_existing=True
        )
        if (
            request is None
            or request.work_order_id != order.id
            or request.status not in ("new", "approved")
        ):
            raise _unprocessable(part_request_id="invalid")

    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max = max_discount(order, items)
    row = WorkOrderPart(
        id=new_id(),
        work_order_id=order.id,
        part_id=part.id if part else None,
        name=name,
        sku=sku,
        unit=unit,
        quantity=data.quantity,
        unit_price=unit_price,
        total=part_total(data.quantity, unit_price),
        added_by=actor.id,
    )
    issued = await stock_service.issue_for_order(
        session,
        order=order,
        part_id=row.part_id,
        quantity=data.quantity,
        actor_id=actor.id,
    )
    if issued is not None:
        row.stock_movement_id, row.unit_cost = issued.movement_id, issued.unit_cost
    session.add(row)
    parts.append(row)
    if request is not None:
        request.status = "issued"
        request.handled_by = actor.id
        request.handled_at = datetime.now(UTC)
    await session.flush()
    await _save(session, actor, order, items, parts, old_max_discount=old_max)
    _audit(
        session,
        actor,
        client_info,
        action="create",
        entity_type="work_order_part",
        entity_id=row.id,
        order=order,
        changes=_created(_part_snapshot(row)),
    )
    await session.commit()
    return await _respond(session, actor, order)


async def update_part(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    row_id: uuid.UUID,
    data: PartUpdate,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, data.version)
    _check_open(order)
    row = await _find_part(session, order, row_id)
    values = data.model_dump(exclude_unset=True)
    values.pop("version")
    if not values:
        return await _respond(session, actor, order)
    if "name" in values and row.part_id is not None:
        raise _unprocessable(name="not_allowed")
    if (
        "unit_price" in values
        and row.part_id is not None
        and values["unit_price"] != row.unit_price
        and actor.role != Role.director
    ):
        raise AppError(403, "forbidden")

    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max = max_discount(order, items)
    old = _part_snapshot(row)
    if "quantity" in values and values["quantity"] != row.quantity and row.part_id is not None:
        await stock_service.return_for_order(session, order=order, part_row=row, actor_id=actor.id)
        issued = await stock_service.issue_for_order(
            session,
            order=order,
            part_id=row.part_id,
            quantity=values["quantity"],
            actor_id=actor.id,
        )
        if issued is not None:
            row.stock_movement_id, row.unit_cost = issued.movement_id, issued.unit_cost
    for name, value in values.items():
        setattr(row, name, value)
    changes = diff(old, _part_snapshot(row))
    if not changes:
        return await _respond(session, actor, order)
    await _save(session, actor, order, items, parts, old_max_discount=old_max)
    _audit(
        session,
        actor,
        client_info,
        action="update",
        entity_type="work_order_part",
        entity_id=row.id,
        order=order,
        changes=changes,
    )
    await session.commit()
    return await _respond(session, actor, order)


async def delete_part(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    row_id: uuid.UUID,
    version: int,
    client_info: ClientInfo,
) -> WorkOrderRead:
    order = await _get_order(session, allowed, order_id, for_update=True)
    _check_version(order, version)
    _check_open(order)
    row = await _find_part(session, order, row_id)
    items = await _items_of(session, order.id)
    parts = await _parts_of(session, order.id)
    old_max = max_discount(order, items)
    snapshot = _part_snapshot(row)
    await stock_service.return_for_order(session, order=order, part_row=row, actor_id=actor.id)
    await session.execute(delete(WorkOrderPart).where(WorkOrderPart.id == row.id))
    session.expunge(row)
    parts = [p for p in parts if p.id != row.id]
    await _save(session, actor, order, items, parts, old_max_discount=old_max)
    _audit(
        session,
        actor,
        client_info,
        action="delete",
        entity_type="work_order_part",
        entity_id=row.id,
        order=order,
        changes={k: {"old": v, "new": None} for k, v in snapshot.items()},
    )
    await session.commit()
    return await _respond(session, actor, order)


# ---------------- комментарии ----------------


async def list_comments(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    is_internal: bool | None,
) -> list[WorkOrderCommentRead]:
    order = await _get_order(session, allowed, order_id)
    stmt = select(WorkOrderComment).where(WorkOrderComment.work_order_id == order.id)
    if is_internal is not None:
        stmt = stmt.where(WorkOrderComment.is_internal.is_(is_internal))
    rows = list(
        await session.scalars(stmt.order_by(WorkOrderComment.created_at, WorkOrderComment.id))
    )
    return await _comment_reads(session, order, rows)


async def _comment_reads(
    session: AsyncSession, order: WorkOrder, rows: list[WorkOrderComment]
) -> list[WorkOrderCommentRead]:
    users = {
        u.id: u
        for u in await session.scalars(
            select(User).where(User.id.in_({r.author_id for r in rows}))
        )
    }
    loc = await session.get(Location, order.location_id)
    tz = _tz(loc) if loc else ZoneInfo("UTC")
    return [
        WorkOrderCommentRead(
            id=r.id,
            item_id=r.item_id,
            author=CommentAuthor(
                id=r.author_id, full_name=users[r.author_id].full_name, role=users[r.author_id].role
            ),
            text=r.text,
            is_internal=r.is_internal,
            created_at=r.created_at.astimezone(tz),
        )
        for r in rows
    ]


async def add_comment(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    data: CommentCreate,
    client_info: ClientInfo,
) -> WorkOrderCommentRead:
    order = await _get_order(session, allowed, order_id)
    item: WorkOrderItem | None = None
    if data.item_id is not None:
        item = await session.get(WorkOrderItem, data.item_id)
        if item is None or item.work_order_id != order.id:
            raise _unprocessable(item_id="invalid")
    comment = WorkOrderComment(
        id=new_id(),
        work_order_id=order.id,
        item_id=data.item_id,
        author_id=actor.id,
        text=data.text,
        is_internal=data.is_internal,
    )
    session.add(comment)
    await session.flush()
    await session.refresh(comment)
    _audit(
        session,
        actor,
        client_info,
        action="create",
        entity_type="work_order_comment",
        entity_id=comment.id,
        order=order,
        changes={
            "item_id": {"old": None, "new": str(data.item_id) if data.item_id else None},
            "is_internal": {"old": None, "new": data.is_internal},
        },
    )
    if item is not None:
        await _publish_item_updated(session, actor, order, item, "comment")
    await session.commit()
    return (await _comment_reads(session, order, [comment]))[0]


async def list_mechanics(
    session: AsyncSession, allowed: list[uuid.UUID], location_id: uuid.UUID
) -> list[UserRef]:
    """Активные механики, привязанные к точке (для выбора исполнителя менеджером)."""
    if location_id not in allowed:
        raise AppError(404, "not_found")
    rows = await session.scalars(
        select(User)
        .join(UserLocation, UserLocation.user_id == User.id)
        .where(
            UserLocation.location_id == location_id,
            User.role == Role.mechanic,
            User.is_active.is_(True),
        )
        .order_by(User.full_name, User.id)
    )
    return [_ref(u) for u in rows]
