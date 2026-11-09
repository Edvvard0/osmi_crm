"""Рабочее место механика (модуль 6): задачи, таймер, комментарии, справочник запчастей.

Механик видит только свои позиции и только в своих точках; чужое, несуществующее и
недоступное — одинаково 404. Цены и контакты клиента в ответы не попадают.
"""

import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, Part, User, Vehicle
from app.models.mechanic import WorkLog
from app.models.work_order import WorkOrder, WorkOrderComment, WorkOrderItem
from app.schemas.mechanic import (
    CommentCreate,
    FinishBody,
    FinishResult,
    MechanicComment,
    MechanicPart,
    MechanicTask,
    MechanicTaskDetail,
    PauseResult,
    StartBody,
    StartResult,
    TaskItemBrief,
    TaskList,
    TaskScope,
    TaskVehicle,
    UserRef,
)
from app.services import events, timers, work_orders
from app.services.audit import ClientInfo, write_audit

WORKABLE = ("diagnostics", "in_progress")
LIST_ORDER_STATUSES = ("new", "diagnostics", "awaiting_approval", "in_progress", "awaiting_parts")
OPEN_ITEM_STATUSES = ("pending", "in_progress", "paused")
LIST_LIMIT = 200
CLOSED_VISIBLE_DAYS = 7
_RANK = {"in_progress": 0, "paused": 1, "pending": 2, "done": 3}
_CENT = Decimal("0.01")


def not_found() -> AppError:
    return AppError(404, "not_found")


# ---------------- загрузка и доступ ----------------


async def load_item(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    item_id: uuid.UUID,
    *,
    lock: bool = False,
    visible_only: bool = True,
) -> tuple[WorkOrderItem, WorkOrder]:
    """Своя позиция в доступной точке. `lock`: заказ FOR UPDATE, затем позиция FOR UPDATE.

    Заказ блокируется эксклюзивно (тот же порядок «заказ → позиции», что в модуле 5): старт
    и завершение меняют заказ (`started_at`, автопереход в `quality_check`). При FOR SHARE два
    механика одного заказа взаимоблокировались бы на повышении блокировки, а при параллельном
    завершении двух последних работ каждый не видел бы чужого `done` — автопереход терялся.

    `visible_only` скрывает (404) отменённые позиции, отменённые заказы и заказы, закрытые
    более 7 дней назад; для действий таймера он выключен (там `invalid_state`).
    """
    item = await session.scalar(
        select(WorkOrderItem).where(
            WorkOrderItem.id == item_id, WorkOrderItem.mechanic_id == user.id
        )
    )
    if item is None:
        raise not_found()
    order_stmt = select(WorkOrder).where(WorkOrder.id == item.work_order_id)
    if lock:
        order_stmt = order_stmt.with_for_update().execution_options(populate_existing=True)
    order = await session.scalar(order_stmt)
    if order is None or order.location_id not in allowed:
        raise not_found()
    if lock:
        # Перечитываем под блокировкой: пока ждали заказ, позицию могли переназначить.
        item = await session.scalar(
            select(WorkOrderItem)
            .where(
                WorkOrderItem.id == item_id,
                WorkOrderItem.mechanic_id == user.id,
                WorkOrderItem.work_order_id == order.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise not_found()
    if visible_only:
        if item.status == "cancelled" or order.status == "cancelled":
            raise not_found()
        if (
            order.status == "closed"
            and order.closed_at is not None
            and order.closed_at < timers.now() - timedelta(days=CLOSED_VISIBLE_DAYS)
        ):
            raise not_found()
    return item, order


# ---------------- сборка ответов ----------------


def _norm_hours(item: WorkOrderItem) -> Decimal:
    return (item.norm_hours * item.quantity).quantize(_CENT, rounding=ROUND_HALF_UP)


def _task_vehicle(v: Vehicle) -> TaskVehicle:
    return TaskVehicle(
        id=v.id, make=v.make, model=v.model, year=v.year, plate_number=v.plate_number, color=v.color
    )


def _task(
    item: WorkOrderItem,
    order: WorkOrder,
    vehicle: Vehicle,
    timer: dict[uuid.UUID, tuple[int, datetime | None]],
    at: datetime,
) -> MechanicTask:
    seconds, running = timer.get(item.id, (0, None))
    return MechanicTask(
        item_id=item.id,
        order_id=order.id,
        order_number=order.number,
        order_status=order.status,
        department=item.department,
        name=item.name,
        quantity=item.quantity,
        norm_hours=_norm_hours(item),
        status=item.status,
        worked_seconds=seconds,
        running_since=running if item.status == "in_progress" else None,
        vehicle=_task_vehicle(vehicle),
        planned_ready_at=order.planned_ready_at,
        is_overdue=(
            order.planned_ready_at is not None
            and order.planned_ready_at < at
            and item.status in OPEN_ITEM_STATUSES
        ),
        can_start=item.status in ("pending", "paused") and order.status in WORKABLE,
        finished_at=item.finished_at,
    )


async def build_task(
    session: AsyncSession, item: WorkOrderItem, order: WorkOrder, at: datetime
) -> MechanicTask:
    vehicle = await session.get(Vehicle, order.vehicle_id)
    assert vehicle is not None
    timer = await timers.worked_seconds(session, [item.id], at)
    return _task(item, order, vehicle, timer, at)


# ---------------- список и карточка ----------------


def _base_select() -> Select[WorkOrderItem, WorkOrder, Vehicle, str]:
    return (
        select(WorkOrderItem, WorkOrder, Vehicle, Location.timezone)
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
        .join(Location, Location.id == WorkOrder.location_id)
    )


def _in_today(
    item: WorkOrderItem, order: WorkOrder, tz: ZoneInfo, today: datetime
) -> bool:
    day = today.date()
    if item.status in ("in_progress", "paused"):
        return True
    if item.status == "pending":
        if order.planned_ready_at is not None:
            return order.planned_ready_at.astimezone(tz).date() <= day
        return order.created_at.astimezone(tz).date() == day
    if item.status == "done":
        return item.finished_at is not None and item.finished_at.astimezone(tz).date() == day
    return False


async def list_tasks(
    session: AsyncSession, user: User, allowed: list[uuid.UUID], scope: TaskScope
) -> TaskList:
    at = timers.now()
    active_row = (
        await session.execute(
            _base_select()
            .join(WorkLog, WorkLog.item_id == WorkOrderItem.id)
            .where(
                WorkLog.mechanic_id == user.id,
                WorkLog.ended_at.is_(None),
                WorkOrder.location_id.in_(allowed),
            )
        )
    ).first()
    active_id = active_row[0].id if active_row else None

    open_cond = (
        WorkOrderItem.status.in_(OPEN_ITEM_STATUSES) & WorkOrder.status.in_(LIST_ORDER_STATUSES)
    )
    cond = open_cond
    if scope == "today":
        # Завершённые позиции берём с запасом в двое суток; точный день — по поясу точки.
        cond = open_cond | (
            (WorkOrderItem.status == "done")
            & (WorkOrderItem.finished_at >= at - timedelta(days=2))
            & (WorkOrder.status != "cancelled")
        )
    stmt = _base_select().where(
        WorkOrderItem.mechanic_id == user.id, WorkOrder.location_id.in_(allowed), cond
    )
    if active_id is not None:
        stmt = stmt.where(WorkOrderItem.id != active_id)
    rows = (await session.execute(stmt)).all()
    if scope == "today":
        rows = [
            r for r in rows if _in_today(r[0], r[1], ZoneInfo(r[3]), at.astimezone(ZoneInfo(r[3])))
        ]
    far = datetime.max.replace(tzinfo=at.tzinfo)
    rows = sorted(
        rows,
        key=lambda r: (
            _RANK.get(r[0].status, 9),
            r[1].planned_ready_at is None,
            r[1].planned_ready_at or far,
            r[1].number,
        ),
    )[:LIST_LIMIT]

    ids = [r[0].id for r in rows] + ([active_id] if active_id else [])
    timer = await timers.worked_seconds(session, ids, at)
    active = _task(active_row[0], active_row[1], active_row[2], timer, at) if active_row else None
    return TaskList(
        active=active,
        items=[_task(i, o, v, timer, at) for i, o, v, _ in rows],
        server_time=at,
    )


async def get_task(
    session: AsyncSession, user: User, allowed: list[uuid.UUID], item_id: uuid.UUID
) -> MechanicTaskDetail:
    at = timers.now()
    item, order = await load_item(session, user, allowed, item_id)
    vehicle = await session.get(Vehicle, order.vehicle_id)
    assert vehicle is not None
    mine = (
        await session.scalars(
            select(WorkOrderItem)
            .where(
                WorkOrderItem.work_order_id == order.id,
                WorkOrderItem.mechanic_id == user.id,
                WorkOrderItem.status != "cancelled",
            )
            .order_by(WorkOrderItem.sort_order, WorkOrderItem.created_at, WorkOrderItem.id)
        )
    ).all()
    timer = await timers.worked_seconds(session, [i.id for i in mine] + [item.id], at)
    base = _task(item, order, vehicle, timer, at)

    latest = (
        select(WorkOrderComment)
        .where(WorkOrderComment.work_order_id == order.id, WorkOrderComment.is_internal.is_(True))
        .order_by(WorkOrderComment.created_at.desc(), WorkOrderComment.id.desc())
        .limit(LIST_LIMIT)
        .subquery()
    )
    comments = (
        await session.execute(
            select(
                latest.c.id,
                latest.c.item_id,
                latest.c.text,
                latest.c.created_at,
                User.id,
                User.full_name,
            )
            .join(User, User.id == latest.c.author_id)
            .order_by(latest.c.created_at, latest.c.id)
        )
    ).all()
    return MechanicTaskDetail(
        **base.model_dump(),
        complaint=order.complaint,
        intake_notes=order.intake_notes,
        mileage_in=order.mileage_in,
        my_items=[
            TaskItemBrief(
                item_id=i.id,
                name=i.name,
                quantity=i.quantity,
                norm_hours=_norm_hours(i),
                status=i.status,
                worked_seconds=timer.get(i.id, (0, None))[0],
                running_since=timer.get(i.id, (0, None))[1] if i.status == "in_progress" else None,
            )
            for i in mine
        ],
        comments=[
            MechanicComment(
                id=c_id,
                item_id=c_item,
                author=UserRef(id=a_id, full_name=a_name),
                text=c_text,
                created_at=c_at,
            )
            for c_id, c_item, c_text, c_at, a_id, a_name in comments
        ],
        server_time=at,
    )


# ---------------- таймер ----------------


def _audit_status(
    session: AsyncSession,
    user: User,
    item: WorkOrderItem,
    order: WorkOrder,
    old: str,
    new: str,
    client: ClientInfo,
) -> None:
    write_audit(
        session,
        action="status_change",
        entity_type="work_order_item",
        entity_id=item.id,
        location_id=order.location_id,
        user_id=user.id,
        changes={"status": {"old": old, "new": new}},
        client=client,
    )


async def _another_active(
    session: AsyncSession, user: User, exclude: uuid.UUID | None
) -> tuple[WorkLog, WorkOrderItem, WorkOrder] | None:
    stmt = (
        select(WorkLog, WorkOrderItem, WorkOrder)
        .join(WorkOrderItem, WorkOrderItem.id == WorkLog.item_id)
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkLog.mechanic_id == user.id, WorkLog.ended_at.is_(None))
    )
    if exclude is not None:
        stmt = stmt.where(WorkLog.item_id != exclude)
    row = (await session.execute(stmt.with_for_update(of=WorkLog))).first()
    return (row[0], row[1], row[2]) if row else None


def _busy_error(item: WorkOrderItem, order: WorkOrder) -> AppError:
    return AppError(
        409,
        "another_task_active",
        details={"item_id": str(item.id), "order_number": order.number, "item_name": item.name},
    )


async def start_task(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    item_id: uuid.UUID,
    data: StartBody,
    client: ClientInfo,
) -> StartResult:
    item, order = await load_item(session, user, allowed, item_id, lock=True, visible_only=False)
    at = timers.now()
    if item.status == "in_progress" and await timers.has_open_log(session, item):
        task = await build_task(session, item, order, at)
        return StartResult(task=task, active=task, server_time=at)
    if item.status not in ("pending", "paused"):
        raise AppError(409, "invalid_state")
    if order.status not in WORKABLE:
        raise AppError(409, "order_not_workable", details={"order_status": order.status})

    other = await _another_active(session, user, item.id)
    if other is not None:
        log, other_item, other_order = other
        if not data.pause_active:
            raise _busy_error(other_item, other_order)
        timers.close_log(log, at)
        old = other_item.status
        other_item.status = "paused"
        await timers.recalc_actual_minutes(session, other_item)
        _audit_status(session, user, other_item, other_order, old, "paused", client)

    old_status = item.status
    try:
        async with session.begin_nested():
            session.add(WorkLog(item_id=item.id, mechanic_id=user.id, started_at=at))
            await session.flush()
    except IntegrityError as exc:
        # Гонка двух стартов: уникальный индекс одной активной работы на механика.
        busy = await _another_active(session, user, item.id)
        if busy is None:
            raise exc
        raise _busy_error(busy[1], busy[2]) from exc
    item.status = "in_progress"
    if item.started_at is None:
        item.started_at = at
    if order.started_at is None:
        order.started_at = at
    _audit_status(session, user, item, order, old_status, "in_progress", client)
    await session.flush()
    task = await build_task(session, item, order, at)
    await session.commit()
    return StartResult(task=task, active=task, server_time=at)


async def pause_task(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    item_id: uuid.UUID,
    client: ClientInfo,
) -> PauseResult:
    item, order = await load_item(session, user, allowed, item_id, lock=True, visible_only=False)
    if item.status != "in_progress":
        raise AppError(409, "invalid_state")
    at = timers.now()
    await timers.close_open_log(session, item)
    item.status = "paused"
    _audit_status(session, user, item, order, "in_progress", "paused", client)
    await session.flush()
    task = await build_task(session, item, order, at)
    await session.commit()
    return PauseResult(task=task, server_time=at)


async def _after_item_done(
    session: AsyncSession,
    order: WorkOrder,
    user: User,
    vehicle: Vehicle,
    item: WorkOrderItem,
    client: ClientInfo,
) -> bool:
    """`on_item_done` модуля 5 (автопереход в `quality_check`) и событие для менеджеров точки.

    При автопереходе публикуется `work_order.ready_for_check`, иначе `work_item.finished`.
    """
    moved = await work_orders.on_item_done(session, order, actor_id=user.id, client_info=client)
    if moved:
        order.version = order.version + 1
        await events.publish(
            session,
            "work_order.ready_for_check",
            {
                "order_id": str(order.id),
                "order_number": order.number,
                "plate_number": vehicle.plate_number,
            },
            location_id=order.location_id,
            actor_id=user.id,
            dedup_key=f"work_order.ready_for_check:{order.id}:{order.version}",
        )
    else:
        await events.publish(
            session,
            "work_item.finished",
            {
                "order_id": str(order.id),
                "order_number": order.number,
                "item_name": item.name,
                "mechanic_name": user.full_name,
                "plate_number": vehicle.plate_number,
            },
            location_id=order.location_id,
            actor_id=user.id,
        )
    return moved


async def finish_task(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    item_id: uuid.UUID,
    data: FinishBody,
    client: ClientInfo,
) -> FinishResult:
    item, order = await load_item(session, user, allowed, item_id, lock=True, visible_only=False)
    at = timers.now()
    if item.status == "done":
        task = await build_task(session, item, order, at)
        return FinishResult(
            task=task, order_status=order.status, order_auto_moved=False, server_time=at
        )
    if item.status not in ("in_progress", "paused"):
        raise AppError(409, "invalid_state")
    if order.status not in WORKABLE:
        raise AppError(409, "order_not_workable", details={"order_status": order.status})

    old_status = item.status
    await timers.close_open_log(session, item)
    item.status = "done"
    item.finished_at = at
    if item.started_at is None:
        item.started_at = at
    await timers.recalc_actual_minutes(session, item)
    _audit_status(session, user, item, order, old_status, "done", client)
    if data.comment:
        comment = WorkOrderComment(
            work_order_id=order.id,
            item_id=item.id,
            author_id=user.id,
            text=data.comment,
            is_internal=True,
            created_at=at,
        )
        session.add(comment)
        await session.flush()
        write_audit(
            session,
            action="create",
            entity_type="work_order_comment",
            entity_id=comment.id,
            location_id=order.location_id,
            user_id=user.id,
            changes={"item_id": str(item.id), "is_internal": True},
            client=client,
        )
    vehicle = await session.get(Vehicle, order.vehicle_id)
    assert vehicle is not None
    moved = await _after_item_done(session, order, user, vehicle, item, client)
    await session.flush()
    task = await build_task(session, item, order, at)
    await session.commit()
    return FinishResult(
        task=task,
        order_status=order.status,
        order_auto_moved=moved,
        server_time=at,
    )


# ---------------- комментарии ----------------


async def add_comment(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    item_id: uuid.UUID,
    data: CommentCreate,
    client: ClientInfo,
) -> MechanicComment:
    item, order = await load_item(session, user, allowed, item_id)
    comment = WorkOrderComment(
        work_order_id=order.id,
        item_id=item.id,
        author_id=user.id,
        text=data.text,
        is_internal=True,
        created_at=timers.now(),
    )
    session.add(comment)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="work_order_comment",
        entity_id=comment.id,
        location_id=order.location_id,
        user_id=user.id,
        changes={"item_id": str(item.id), "is_internal": True},
        client=client,
    )
    await session.commit()
    return MechanicComment(
        id=comment.id,
        item_id=item.id,
        author=UserRef(id=user.id, full_name=user.full_name),
        text=comment.text,
        created_at=comment.created_at,
    )


# ---------------- справочник запчастей без цен ----------------


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_parts(session: AsyncSession, search: str, limit: int) -> list[MechanicPart]:
    pattern = f"%{_like_escape(search.strip())}%"
    rows = (
        await session.scalars(
            select(Part)
            .where(
                Part.is_active.is_(True),
                Part.name.ilike(pattern, escape="\\")
                | Part.sku.ilike(pattern, escape="\\")
                | Part.brand.ilike(pattern, escape="\\"),
            )
            .order_by(Part.name, Part.id)
            .limit(limit)
        )
    ).all()
    return [
        MechanicPart(id=p.id, sku=p.sku, name=p.name, brand=p.brand, unit=p.unit) for p in rows
    ]
