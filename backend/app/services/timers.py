"""Таймер механика (модуль 6): интервалы `work_logs`, подсчёт `actual_minutes`.

Время берёт только сервер. Системные часы Python, а не `now()` БД: в рамках одной транзакции
`now()` постоянно, и интервал получился бы нулевым (CHECK `ended_at > started_at`).
Функции `pause_all`, `close_open_log`, `has_open_log` вызывает модуль 5 при смене статуса заказа
и отмене позиции; `version` заказа они не меняют.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mechanic import WorkLog
from app.models.work_order import WorkOrder, WorkOrderItem

_MICRO = timedelta(microseconds=1)


def now() -> datetime:
    return datetime.now(UTC)


def _round_minutes(seconds: Decimal) -> int:
    return int((seconds / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def close_log(log: WorkLog, at: datetime) -> None:
    # `ended_at` строго больше `started_at` (CHECK в БД), даже при совпадении часов.
    log.ended_at = at if at > log.started_at else log.started_at + _MICRO


async def logged_seconds(session: AsyncSession, item_id: uuid.UUID) -> Decimal:
    """Сумма длительностей закрытых интервалов позиции, секунды."""
    value = await session.scalar(
        select(
            func.coalesce(
                func.sum(func.extract("epoch", WorkLog.ended_at - WorkLog.started_at)), 0
            )
        ).where(WorkLog.item_id == item_id, WorkLog.ended_at.is_not(None))
    )
    return Decimal(value or 0)


async def recalc_actual_minutes(session: AsyncSession, item: WorkOrderItem) -> int:
    """`actual_minutes` = округлённая (ROUND_HALF_UP) сумма закрытых интервалов, минуты."""
    await session.flush()
    minutes = _round_minutes(await logged_seconds(session, item.id))
    item.actual_minutes = minutes
    return minutes


async def open_log(session: AsyncSession, item_id: uuid.UUID) -> WorkLog | None:
    return await session.scalar(
        select(WorkLog).where(WorkLog.item_id == item_id, WorkLog.ended_at.is_(None))
    )


async def _close_logs(session: AsyncSession, item_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(item_ids)
    if not ids:
        return set()
    logs = (
        await session.scalars(
            select(WorkLog)
            .where(WorkLog.item_id.in_(ids), WorkLog.ended_at.is_(None))
            .with_for_update()
        )
    ).all()
    at = now()
    for log in logs:
        close_log(log, at)
    return {log.item_id for log in logs}


async def pause_all(session: AsyncSession, order: WorkOrder) -> None:
    """Закрывает открытые интервалы работ заказа; позиции `in_progress` -> `paused`."""
    items = (
        await session.scalars(
            select(WorkOrderItem).where(WorkOrderItem.work_order_id == order.id)
        )
    ).all()
    closed = await _close_logs(session, (i.id for i in items))
    for item in items:
        if item.status == "in_progress":
            item.status = "paused"
        if item.id in closed:
            await recalc_actual_minutes(session, item)
    await session.flush()


async def close_open_log(session: AsyncSession, item: WorkOrderItem) -> None:
    """Закрывает открытый интервал таймера позиции и пересчитывает `actual_minutes`."""
    closed = await _close_logs(session, [item.id])
    if closed:
        await recalc_actual_minutes(session, item)


async def has_open_log(session: AsyncSession, item: WorkOrderItem) -> bool:
    """Есть ли у позиции открытый интервал таймера."""
    return await open_log(session, item.id) is not None


async def worked_seconds(
    session: AsyncSession, item_ids: Iterable[uuid.UUID], at: datetime
) -> dict[uuid.UUID, tuple[int, datetime | None]]:
    """По позициям: (отработанные секунды на момент `at`, начало открытого интервала)."""
    ids = list(item_ids)
    if not ids:
        return {}
    duration = func.coalesce(WorkLog.ended_at, at) - WorkLog.started_at
    rows = (
        await session.execute(
            select(
                WorkLog.item_id,
                func.coalesce(func.sum(func.extract("epoch", duration)), 0),
                func.max(WorkLog.started_at).filter(WorkLog.ended_at.is_(None)),
            )
            .where(WorkLog.item_id.in_(ids))
            .group_by(WorkLog.item_id)
        )
    ).all()
    return {item_id: (max(int(secs), 0), running) for item_id, secs, running in rows}
