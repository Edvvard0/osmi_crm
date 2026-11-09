"""Готовность и состояние системы: health/ready, GET /system/status, heartbeat воркера (M12)."""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import structlog
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.system_settings import SystemSetting
from app.models.telegram import NotificationOutbox
from app.schemas.system import (
    CheckDb,
    CheckMigrations,
    CheckOutbox,
    CheckWorker,
    Ready,
    ReadyChecks,
    StatusMigrations,
    StatusOutbox,
    StatusTelegram,
    StatusWorker,
    SystemStatus,
)

log = structlog.get_logger()

HEARTBEAT_KEY = "_worker_heartbeat"
DB_TIMEOUT_SECONDS = 2.0
READY_CACHE_SECONDS = 2.0
_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


@lru_cache
def head_revision() -> str:
    """Единственная голова скриптов миграций (вычисляется один раз за процесс)."""
    try:
        heads = ScriptDirectory(str(_MIGRATIONS_DIR)).get_heads()
    except Exception:
        log.error("migrations_scripts_unavailable")
        return "unknown"
    return heads[0] if len(heads) == 1 else "unknown"


async def _query[T](
    session: AsyncSession, fn: Callable[[], Awaitable[T]], default: T
) -> tuple[T, bool]:
    """Запрос в SAVEPOINT с таймаутом: сбой одной проверки (например, нет таблицы) не ломает
    остальные. Возвращает (результат | default, выполнен ли запрос)."""
    try:
        async with asyncio.timeout(DB_TIMEOUT_SECONDS):
            async with session.begin_nested():
                return await fn(), True
    except Exception as exc:  # TimeoutError, DBAPIError, соединение недоступно
        log.warning("status_check_failed", error=type(exc).__name__)
        return default, False


async def check_db(session: AsyncSession) -> bool:
    _, ok = await _query(session, lambda: session.execute(text("SELECT 1")), None)
    return ok


async def current_revision(session: AsyncSession) -> str | None:
    async def fn() -> str | None:
        value = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        return None if value is None else str(value)

    value, _ = await _query(session, fn, None)
    return value


def _parse_at(value: Any) -> datetime | None:
    raw = value.get("at") if isinstance(value, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


async def last_heartbeat(session: AsyncSession) -> datetime | None:
    async def fn() -> Any:
        return await session.scalar(
            select(SystemSetting.value).where(SystemSetting.key == HEARTBEAT_KEY)
        )

    value, _ = await _query(session, fn, None)
    return _parse_at(value)


async def write_heartbeat(session: AsyncSession, now: datetime | None = None) -> datetime:
    """Записывает `_worker_heartbeat = {"at": iso, "pid": int}` (UPSERT)."""
    at = now or datetime.now(UTC)
    value = {"at": at.isoformat(), "pid": os.getpid()}
    stmt = insert(SystemSetting).values(key=HEARTBEAT_KEY, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SystemSetting.key],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
    )
    await session.execute(stmt)
    return at


def _age_seconds(then: datetime | None, now: datetime) -> int | None:
    return None if then is None else max(0, int((now - then).total_seconds()))


def worker_is_fresh(at: datetime | None, now: datetime, settings: Settings) -> bool:
    age = _age_seconds(at, now)
    return age is not None and age <= settings.ready_worker_max_age_seconds


async def heartbeat_is_fresh(session: AsyncSession) -> bool:
    """Для `python -m app.worker --healthcheck`."""
    return worker_is_fresh(await last_heartbeat(session), datetime.now(UTC), get_settings())


async def outbox_stats(
    session: AsyncSession, now: datetime
) -> tuple[int, datetime | None, int, bool]:
    """(pending, самый старый pending, failed за 24 ч, запрос выполнен)."""

    async def fn() -> tuple[int, datetime | None, int]:
        pending, oldest = (
            await session.execute(
                select(func.count(), func.min(NotificationOutbox.created_at)).where(
                    NotificationOutbox.status == "pending"
                )
            )
        ).one()
        failed = await session.scalar(
            select(func.count()).where(
                NotificationOutbox.status == "failed",
                NotificationOutbox.created_at >= now - timedelta(hours=24),
            )
        )
        return int(pending), oldest, int(failed or 0)

    empty: tuple[int, datetime | None, int] = (0, None, 0)
    (pending, oldest, failed), ok = await _query(session, fn, empty)
    return pending, oldest, failed, ok


# ---------- health/ready ----------

_ready_cache: tuple[float, Ready] | None = None


def reset_ready_cache() -> None:
    global _ready_cache
    _ready_cache = None


async def build_ready(session: AsyncSession) -> Ready:
    settings = get_settings()
    now = datetime.now(UTC)
    head = head_revision()
    db_ok = await check_db(session)
    current: str | None = None
    heartbeat: datetime | None = None
    pending, oldest, outbox_queried = 0, None, False
    if db_ok:
        current = await current_revision(session)
        heartbeat = await last_heartbeat(session)
        pending, oldest, _, outbox_queried = await outbox_stats(session, now)

    migrations_ok = db_ok and current is not None and current == head
    worker_ok = worker_is_fresh(heartbeat, now, settings)
    oldest_age = _age_seconds(oldest, now)
    telegram_off = settings.telegram_mode == "off"
    outbox_ok = telegram_off or (
        outbox_queried
        and (oldest_age is None or oldest_age <= settings.ready_outbox_max_age_seconds)
    )

    status: Literal["ok", "degraded", "down"]
    if not db_ok or not migrations_ok:
        status = "down"
    elif (not telegram_off and not worker_ok) or not outbox_ok:
        status = "degraded"
    else:
        status = "ok"
    return Ready(
        status=status,
        checks=ReadyChecks(
            db=CheckDb(ok=db_ok),
            migrations=CheckMigrations(ok=migrations_ok, current=current, head=head),
            worker=CheckWorker(ok=worker_ok, heartbeat_age_seconds=_age_seconds(heartbeat, now)),
            outbox=CheckOutbox(
                ok=outbox_ok, pending=pending, oldest_pending_age_seconds=oldest_age
            ),
        ),
    )


async def get_ready(session: AsyncSession) -> Ready:
    """Готовность с кэшем в процессе на 2 с."""
    global _ready_cache
    cached = _ready_cache
    if cached is not None and time.monotonic() - cached[0] < READY_CACHE_SECONDS:
        return cached[1]
    ready = await build_ready(session)
    _ready_cache = (time.monotonic(), ready)
    return ready


# ---------- GET /system/status ----------


def _read_marker_mtime(path: str) -> datetime | None:
    if not path:
        return None
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=UTC)
    except OSError:
        return None


async def build_status(session: AsyncSession) -> SystemStatus:
    settings = get_settings()
    now = datetime.now(UTC)
    current = await current_revision(session)
    heartbeat = await last_heartbeat(session)
    pending, oldest, failed, _ = await outbox_stats(session, now)
    backup_at = await asyncio.to_thread(_read_marker_mtime, settings.backup_marker_path)
    mode: Literal["disabled", "polling", "webhook"] = (
        "disabled" if settings.telegram_mode == "off" else settings.telegram_mode
    )
    return SystemStatus(
        server_time=now,
        app_timezone=settings.app_timezone,
        env=settings.env,
        migrations=StatusMigrations(current=current, head=head_revision()),
        worker=StatusWorker(
            last_heartbeat_at=heartbeat, ok=worker_is_fresh(heartbeat, now, settings)
        ),
        outbox=StatusOutbox(
            pending=pending,
            failed_24h=failed,
            oldest_pending_age_seconds=_age_seconds(oldest, now),
        ),
        telegram=StatusTelegram(mode=mode, bot_username=settings.telegram_bot_username or None),
        last_backup_at=backup_at,
        version=settings.app_version,
    )
