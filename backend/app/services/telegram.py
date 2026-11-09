"""Привязка Telegram, настройки уведомлений, тест чата точки (api-contract-m7.md)."""

import secrets
import uuid
from datetime import timedelta
from html import escape

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import RateLimiter
from app.core.security import hash_token
from app.models import Location, User
from app.models.telegram import NotificationOutbox, NotificationSetting, TelegramLinkCode
from app.schemas.telegram import (
    LinkCode,
    NotificationSettingsPatch,
    TelegramStatus,
)
from app.schemas.telegram import (
    NotificationSetting as NotificationSettingRead,
)
from app.services import telegram_client
from app.services.audit import ClientInfo, write_audit
from app.services.notification_catalog import CATALOG, ROLE_EVENTS
from app.services.sessions import utcnow

log = structlog.get_logger()

# Алфавит кода: A-Z без O, I, L и цифры 2-9 (без 0 и 1).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL = timedelta(minutes=10)

link_code_limiter = RateLimiter()  # 5 в минуту на пользователя
test_limiter = RateLimiter()  # 5 в минуту на пользователя
bot_link_limiter = RateLimiter()  # 10 в минуту на chat_id

TEST_TIMEOUT = 5.0


def code_hash(code: str) -> str:
    return hash_token(code.strip().upper())


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def status_of(user: User) -> TelegramStatus:
    settings = get_settings()
    enabled = settings.telegram_enabled
    return TelegramStatus(
        enabled=enabled,
        bot_username=(settings.telegram_bot_username or None) if enabled else None,
        linked=user.telegram_chat_id is not None,
        telegram_username=user.telegram_username,
    )


async def create_link_code(session: AsyncSession, user: User) -> LinkCode:
    settings = get_settings()
    if not settings.telegram_enabled:
        raise AppError(409, "telegram_disabled")
    if user.telegram_chat_id is not None:
        raise AppError(409, "already_linked")
    if not link_code_limiter.allow(str(user.id), 5):
        raise AppError(429, "rate_limited")
    # Блокировка строки пользователя: параллельные запросы не оставят двух действующих кодов,
    # а привязка, завершившаяся между запросами, будет видна.
    await session.refresh(user, with_for_update=True)
    if user.telegram_chat_id is not None:
        raise AppError(409, "already_linked")
    now = utcnow()
    # Предыдущие неиспользованные коды аннулируются.
    await session.execute(
        update(TelegramLinkCode)
        .where(TelegramLinkCode.user_id == user.id, TelegramLinkCode.used_at.is_(None))
        .values(used_at=now)
    )
    code = new_code()
    expires = now + CODE_TTL
    session.add(TelegramLinkCode(user_id=user.id, code_hash=code_hash(code), expires_at=expires))
    await session.commit()
    link = f"https://t.me/{settings.telegram_bot_username}?start={code}"
    return LinkCode(code=code, link=link, expires_at=expires)


async def unlink_user(
    session: AsyncSession, user: User, client: ClientInfo | None = None
) -> bool:
    """Отвязка: очищает чат, `pending`-сообщения пользователя -> `skipped`. Не коммитит."""
    if user.telegram_chat_id is None and user.telegram_username is None:
        return False
    was_linked = user.telegram_chat_id is not None
    user.telegram_chat_id = None
    user.telegram_username = None
    await session.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.user_id == user.id, NotificationOutbox.status == "pending")
        .values(status="skipped", last_error="unlinked")
    )
    if was_linked:
        write_audit(
            session,
            action="update",
            entity_type="user",
            user_id=user.id,
            entity_id=user.id,
            changes={"telegram_linked": {"old": True, "new": False}},
            client=client,
        )
    return was_linked


async def unlink(session: AsyncSession, user: User, client: ClientInfo) -> None:
    await session.refresh(user, with_for_update=True)
    await unlink_user(session, user, client)
    await session.commit()


# ---------------- настройки уведомлений ----------------


async def list_settings(session: AsyncSession, user: User) -> list[NotificationSettingRead]:
    events = ROLE_EVENTS.get(user.role, ())
    explicit = {
        r.event_type: r.is_enabled
        for r in await session.scalars(
            select(NotificationSetting).where(NotificationSetting.user_id == user.id)
        )
    }
    return [
        NotificationSettingRead(
            event_type=et,
            title=CATALOG[et].title,
            description=CATALOG[et].description,
            is_enabled=explicit.get(et, True),
            is_default=et not in explicit,
        )
        for et in events
    ]


async def patch_settings(
    session: AsyncSession, user: User, data: NotificationSettingsPatch
) -> list[NotificationSettingRead]:
    allowed = set(ROLE_EVENTS.get(user.role, ()))
    seen: set[str] = set()
    for item in data.items:
        if item.event_type not in allowed or item.event_type in seen:
            raise AppError(422, "validation_error", {"items": "unknown_event"})
        seen.add(item.event_type)
    stmt = pg_insert(NotificationSetting).values(
        [
            {"user_id": user.id, "event_type": i.event_type, "is_enabled": i.is_enabled}
            for i in data.items
        ]
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "event_type"],
            set_={"is_enabled": stmt.excluded.is_enabled},
        )
    )
    await session.commit()
    return await list_settings(session, user)


# ---------------- тест чата точки ----------------


async def test_location_chat(
    session: AsyncSession, actor: User, location_id: uuid.UUID
) -> None:
    if not get_settings().telegram_enabled:
        raise AppError(409, "telegram_disabled")
    loc = await session.get(Location, location_id)
    if loc is None:
        raise AppError(404, "not_found")
    if loc.telegram_chat_id is None:
        raise AppError(422, "validation_error", {"telegram_chat_id": "required"})
    if not test_limiter.allow(str(actor.id), 5):
        raise AppError(429, "rate_limited")
    client = telegram_client.get_client()
    if client is None:  # pragma: no cover - проверено выше
        raise AppError(409, "telegram_disabled")
    try:
        await client.send_message(
            loc.telegram_chat_id,
            f"Проверка связи: точка {escape(loc.name, quote=False)}",
            timeout=TEST_TIMEOUT,
        )
    except telegram_client.TelegramError as exc:
        log.warning("telegram_test_failed", kind=exc.kind)
        raise AppError(502, "telegram_unavailable") from None
