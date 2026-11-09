"""Реестр периодических задач воркера и запуск под PostgreSQL advisory lock (api-contract-m7.md).

Модули 10-12 регистрируют задачи так же, как модуль 7: кладут файл `app/tasks/<имя>.py`,
который при импорте вызывает `register(...)`. Воркер подгружает все модули пакета `app.tasks`.
Функция задачи — `async def task() -> None` без аргументов (свою сессию БД она открывает через
`session_scope()`).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings

log = structlog.get_logger()

TaskFunc = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    func: TaskFunc
    interval: float | None = None  # секунды между запусками
    daily_at: time | None = None  # ежедневно в это местное время APP_TIMEZONE


REGISTRY: dict[str, PeriodicTask] = {}


def register(
    name: str,
    func: TaskFunc,
    *,
    interval: float | None = None,
    daily_at: time | None = None,
) -> PeriodicTask:
    """Регистрирует задачу; повторная регистрация того же имени заменяет прежнюю."""
    if (interval is None) == (daily_at is None):
        raise ValueError("укажите ровно одно из interval / daily_at")
    if interval is not None and interval <= 0:
        raise ValueError("interval должен быть положительным")
    task = PeriodicTask(name, func, interval, daily_at)
    REGISTRY[name] = task
    return task


@contextlib.asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия БД для задач воркера."""
    db.get_engine()
    assert db._maker is not None
    async with db._maker() as session:
        yield session


@contextlib.asynccontextmanager
async def advisory_lock(name: str) -> AsyncIterator[bool]:
    """Сессионная advisory-блокировка на выделенном соединении; даёт True, если взята."""
    engine = db.get_engine()
    async with engine.connect() as conn:
        got = bool(
            (
                await conn.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": name}
                )
            ).scalar()
        )
        await conn.commit()
        try:
            yield got
        finally:
            if got:
                with contextlib.suppress(Exception):
                    await conn.execute(
                        text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": name}
                    )
                    await conn.commit()


async def run_once(task: PeriodicTask) -> bool:
    """Один запуск под блокировкой. False — блокировку держит другой экземпляр воркера."""
    async with advisory_lock(task.name) as got:
        if not got:
            return False
        try:
            await task.func()
        except Exception as exc:  # задача не должна останавливать цикл
            log.error("task_failed", task=task.name, error=type(exc).__name__)
    return True


def next_daily_run(now: datetime, at: time, tz_name: str) -> datetime:
    """Ближайший момент (UTC) строго после `now`, когда местное время равно `at`."""
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz)
    candidate = datetime.combine(local.date(), at, tzinfo=tz)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), at, tzinfo=tz)
    return candidate.astimezone(UTC)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Ждёт `seconds` или сигнала остановки; True, если остановка запрошена."""
    if seconds > 0:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
    return stop.is_set()


async def run_loop(task: PeriodicTask, stop: asyncio.Event) -> None:
    """Цикл одной задачи; на остановку текущая итерация дорабатывается."""
    if task.interval is not None:
        while not stop.is_set():
            await run_once(task)
            if await _sleep_or_stop(stop, task.interval):
                return
    else:
        assert task.daily_at is not None
        tz_name = get_settings().app_timezone
        while not stop.is_set():
            wait = (
                next_daily_run(datetime.now(UTC), task.daily_at, tz_name) - datetime.now(UTC)
            ).total_seconds()
            if await _sleep_or_stop(stop, wait):
                return
            await run_once(task)
            # Защита от повторного срабатывания в ту же секунду.
            if await _sleep_or_stop(stop, 1):
                return


async def run_all(stop: asyncio.Event, tasks: list[PeriodicTask] | None = None) -> None:
    items = list(REGISTRY.values()) if tasks is None else tasks
    await asyncio.gather(*(run_loop(t, stop) for t in items))
