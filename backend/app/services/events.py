"""Доменные события -> notification_outbox (модуль 7).

`publish` вызывается модулем-владельцем в транзакции бизнес-изменения и сам ничего не коммитит.
Получателей определяет этот модуль (api-contract-m7.md, «Каталог событий»).
"""

import hashlib
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Location, User, UserLocation
from app.models.telegram import NotificationOutbox, NotificationSetting
from app.services.notification_catalog import CATALOG, EventDef, truncate

log = structlog.get_logger()

_DEDUP_MAX = 120


def _dedup(base: str | None, recipient: str) -> str | None:
    if base is None:
        return None
    key = f"{base}:{recipient}"
    if len(key) > _DEDUP_MAX:
        digest = hashlib.sha256(key.encode()).hexdigest()[:40]
        key = f"{key[: _DEDUP_MAX - 41]}:{digest}"
    return key


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _order_info(
    session: AsyncSession, payload: dict[str, Any]
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """(manager_id, location_id) заказа из `payload['order_id']`."""
    order_id = _as_uuid(payload.get("order_id"))
    if order_id is None:
        return None, None
    row = (
        await session.execute(
            text("SELECT manager_id, location_id FROM work_orders WHERE id = :id"),
            {"id": order_id},
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def _recipients(
    session: AsyncSession,
    ev: EventDef,
    payload: dict[str, Any],
    location_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None,
) -> list[User]:
    """Активные привязанные к Telegram пользователи, подходящие по правилам события."""
    stmt = select(User).where(User.is_active.is_(True), User.telegram_chat_id.is_not(None))
    kind = ev.recipients
    if kind in ("target", "order_manager"):
        user_id = target_user_id
        if kind == "order_manager" and user_id is None:
            user_id, order_loc = await _order_info(session, payload)
            location_id = location_id or order_loc
        if user_id is None:
            return []
        stmt = stmt.where(User.id == user_id)
        if location_id is not None:
            # Менеджер/механик получают события только своих точек; директор — любых.
            bound = select(UserLocation.user_id).where(
                UserLocation.user_id == user_id, UserLocation.location_id == location_id
            )
            stmt = stmt.where((User.role == "director") | User.id.in_(bound))
    elif kind in ("location_managers", "location_managers_except_actor"):
        if location_id is None:
            return []
        stmt = stmt.where(
            User.role == "manager",
            User.id.in_(select(UserLocation.user_id).where(UserLocation.location_id == location_id)),
        )
        if kind == "location_managers_except_actor" and actor_id is not None:
            stmt = stmt.where(User.id != actor_id)
    elif kind == "directors":
        stmt = stmt.where(User.role == "director")
    else:  # pragma: no cover - каталог статичен
        return []
    return list(await session.scalars(stmt.order_by(User.id)))


async def _enabled_users(session: AsyncSession, users: list[User], event_type: str) -> list[User]:
    if not users:
        return []
    rows = await session.execute(
        select(NotificationSetting.user_id, NotificationSetting.is_enabled).where(
            NotificationSetting.user_id.in_([u.id for u in users]),
            NotificationSetting.event_type == event_type,
        )
    )
    explicit = {uid: enabled for uid, enabled in rows}
    return [u for u in users if explicit.get(u.id, True)]


async def _publish(
    session: AsyncSession,
    ev: EventDef,
    payload: dict[str, Any],
    location_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None,
    dedup_key: str | None,
) -> None:
    loc = await session.get(Location, location_id) if location_id is not None else None
    tz = ZoneInfo(loc.timezone if loc is not None else get_settings().app_timezone)
    body = truncate(ev.render(payload, tz))

    users = await _recipients(session, ev, payload, location_id, actor_id, target_user_id)
    users = await _enabled_users(session, users, ev.event_type)

    rows: list[dict[str, Any]] = [
        {
            "event_type": ev.event_type,
            "user_id": u.id,
            "chat_id": u.telegram_chat_id,
            "payload": payload,
            "text": body,
            "dedup_key": _dedup(dedup_key, str(u.id)),
        }
        for u in users
    ]
    if ev.group and loc is not None and loc.telegram_chat_id is not None:
        rows.append(
            {
                "event_type": ev.event_type,
                "user_id": None,
                "chat_id": loc.telegram_chat_id,
                "payload": payload,
                "text": body,
                "dedup_key": _dedup(dedup_key, f"chat:{loc.telegram_chat_id}"),
            }
        )
    if not rows:
        return
    stmt = (
        pg_insert(NotificationOutbox)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=[NotificationOutbox.dedup_key],
            index_where=NotificationOutbox.dedup_key.is_not(None),
        )
    )
    await session.execute(stmt)


async def publish(
    session: AsyncSession,
    event_type: str,
    payload: dict[str, str | int | None],
    *,
    location_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None = None,
    dedup_key: str | None = None,
) -> None:
    """Пишет сообщения в notification_outbox (по строке на получателя и на чат точки).

    Telegram выключен -> ничего не пишет. Ошибка публикации не ломает бизнес-транзакцию
    (изолирована SAVEPOINT) и логируется без персональных данных.
    """
    if not get_settings().telegram_enabled:
        return
    ev = CATALOG.get(event_type)
    if ev is None:
        log.warning("event_unknown", event_type=event_type[:50])
        return
    try:
        async with session.begin_nested():
            await _publish(session, ev, payload, location_id, actor_id, target_user_id, dedup_key)
    except Exception as exc:
        log.error("event_publish_failed", event_type=event_type, error=type(exc).__name__)
