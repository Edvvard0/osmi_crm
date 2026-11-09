"""Системные настройки: аксессор `get_setting` (кэш процесса, TTL ≤ 10 с) и чтение/изменение (D-09)."""

import copy
import time
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_defaults import DEFAULTS
from app.models import User
from app.models.system_settings import SystemSetting
from app.schemas.audit import UserRef
from app.schemas.system_settings import Heatmap, SettingsPatch, SettingsRead
from app.services.audit import ClientInfo, diff, write_audit

log = structlog.get_logger()

CACHE_TTL = 10.0
_cache: dict[str, Any] | None = None
_loaded_at = 0.0


def invalidate_cache() -> None:
    """Сбрасывает кэш этого процесса; остальные процессы подхватят значения за TTL."""
    global _cache
    _cache = None


async def _load_all(session: AsyncSession) -> dict[str, Any]:
    global _cache, _loaded_at
    now = time.monotonic()
    if _cache is not None and now - _loaded_at < CACHE_TTL:
        return _cache
    try:
        # SAVEPOINT: сбой чтения (например, таблицы ещё нет) не портит транзакцию вызывающего.
        async with session.begin_nested():
            rows = (await session.execute(select(SystemSetting.key, SystemSetting.value))).all()
    except DBAPIError:
        log.warning("system_settings_unavailable")
        rows = []
    _cache = {key: value for key, value in rows}
    _loaded_at = now
    return _cache


async def get_setting(session: AsyncSession, key: str) -> Any:
    """Значение настройки: из `system_settings`, иначе значение по умолчанию."""
    stored = await _load_all(session)
    if key in stored:
        return copy.deepcopy(stored[key])
    if key in DEFAULTS:
        return copy.deepcopy(DEFAULTS[key])
    if key.startswith("_"):  # служебные ключи воркера
        return None
    raise KeyError(key)


async def read_settings(session: AsyncSession) -> SettingsRead:
    """Текущие значения напрямую из БД (без кэша), без служебных ключей `_*`."""
    rows = (
        await session.execute(
            select(SystemSetting.key, SystemSetting.value, SystemSetting.updated_at)
            .where(SystemSetting.key.in_(list(DEFAULTS)))
            .order_by(SystemSetting.updated_at.desc(), SystemSetting.key)
        )
    ).all()
    values: dict[str, Any] = copy.deepcopy(DEFAULTS)
    for key, value, _ in rows:
        values[key] = value
    updated_at = rows[0][2] if rows else None
    updated_by: UserRef | None = None
    if rows:
        user = await session.scalar(
            select(User)
            .join(SystemSetting, SystemSetting.updated_by == User.id)
            .where(SystemSetting.key == rows[0][0])
        )
        if user is not None:
            updated_by = UserRef(id=user.id, full_name=user.full_name)
    return SettingsRead(
        discount_alert_percent=values["discount_alert_percent"],
        daily_summary_time=values["daily_summary_time"],
        session_retention_days=values["session_retention_days"],
        heatmap_thresholds=Heatmap(**values["heatmap_thresholds"]),
        updated_at=updated_at,
        updated_by=updated_by,
    )


async def update_settings(
    session: AsyncSession, actor_id: uuid.UUID, data: SettingsPatch, client: ClientInfo
) -> SettingsRead:
    patch: dict[str, Any] = data.model_dump(exclude_unset=True)
    stored = {
        key: value
        for key, value in (
            await session.execute(
                select(SystemSetting.key, SystemSetting.value)
                .where(SystemSetting.key.in_(list(patch)))
                .with_for_update()
            )
        ).all()
    }
    old = {key: stored.get(key, copy.deepcopy(DEFAULTS[key])) for key in patch}
    changes = diff(old, patch)
    for key in changes:
        stmt = pg_insert(SystemSetting).values(
            key=key, value=patch[key], updated_by=actor_id, updated_at=func.clock_timestamp()
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={
                    "value": stmt.excluded.value,
                    "updated_by": stmt.excluded.updated_by,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="system_settings",
            user_id=actor_id,
            changes=changes,
            client=client,
        )
    await session.commit()
    invalidate_cache()
    return await read_settings(session)
