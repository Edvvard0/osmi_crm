"""Бот: обработка Update (привязка аккаунта, /stop, /chatid, справка). api-contract-m7.md."""

import html
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.telegram import TelegramLinkCode
from app.services import telegram as tg
from app.services import telegram_client
from app.services.audit import write_audit
from app.services.sessions import utcnow

log = structlog.get_logger()

BAD_CODE = "Код не подходит или устарел. Получите новый в разделе «Настройки»"
CHAT_TAKEN = "Этот чат уже привязан к другому сотруднику"
HELP = (
    "Чтобы привязать аккаунт, откройте раздел «Настройки» в системе, получите код и отправьте "
    "его командой /start КОД.\nОтключить уведомления в этом чате: /stop"
)
NOT_LINKED = "Этот чат не привязан ни к одному аккаунту"


def _parse_command(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    if not parts or not parts[0].startswith("/"):
        return "", ""
    cmd = parts[0][1:].split("@", 1)[0].lower()
    return cmd, parts[1].strip() if len(parts) > 1 else ""


async def _bind(
    session: AsyncSession, chat_id: int, username: str | None, code: str
) -> str:
    row = await session.scalar(
        select(TelegramLinkCode)
        .where(TelegramLinkCode.code_hash == tg.code_hash(code))
        .with_for_update()
    )
    now = utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now:
        return BAD_CODE
    user = await session.get(User, row.user_id, with_for_update=True)
    if user is None or not user.is_active:
        return BAD_CODE
    other = await session.scalar(
        select(User.id).where(User.telegram_chat_id == chat_id, User.id != user.id)
    )
    if other is not None:
        return CHAT_TAKEN
    was_linked = user.telegram_chat_id is not None
    user.telegram_chat_id = chat_id
    user.telegram_username = username
    row.used_at = now
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # Гонка: чат успели привязать к другому сотруднику (SAVEPOINT уже откатился).
        return CHAT_TAKEN
    write_audit(
        session,
        action="update",
        entity_type="user",
        user_id=user.id,
        entity_id=user.id,
        changes={"telegram_linked": {"old": was_linked, "new": True}},
    )
    await session.commit()
    return f"Готово, {html.escape(user.full_name, quote=False)}. Уведомления включены"


async def _stop(session: AsyncSession, chat_id: int) -> str:
    user = await session.scalar(
        select(User).where(User.telegram_chat_id == chat_id).with_for_update()
    )
    if user is None:
        return NOT_LINKED
    await tg.unlink_user(session, user)
    await session.commit()
    return "Готово. Уведомления в этом чате отключены"


async def process_update(session: AsyncSession, update: dict[str, Any]) -> tuple[int, str] | None:
    """Разбирает Update; возвращает `(chat_id, ответ)` или None, если отвечать не нужно."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    text = message.get("text")
    if not isinstance(chat, dict) or not isinstance(text, str):
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool):
        return None
    cmd, arg = _parse_command(text)
    if not cmd:
        return None
    if cmd == "chatid":  # в любом типе чата
        return chat_id, f"ID этого чата: {chat_id}"
    if chat.get("type") != "private":
        return None
    if cmd == "start" and arg:
        if not tg.bot_link_limiter.allow(str(chat_id), 10):
            return None
        sender = message.get("from")
        username = sender.get("username") if isinstance(sender, dict) else None
        if not isinstance(username, str):
            username = None
        return chat_id, await _bind(session, chat_id, username[:64] if username else None, arg)
    if cmd in ("start", "help"):
        return chat_id, HELP
    if cmd == "stop":
        return chat_id, await _stop(session, chat_id)
    return None


async def handle_update(session: AsyncSession, update: dict[str, Any]) -> None:
    """Обрабатывает Update и отправляет ответ напрямую (минуя outbox). Ошибки не пробрасываются."""
    try:
        reply = await process_update(session, update)
    except Exception as exc:
        await session.rollback()
        log.error("telegram_update_failed", error=type(exc).__name__)
        return
    if reply is None:
        return
    client = telegram_client.get_client()
    if client is None:
        return
    try:
        await client.send_message(reply[0], reply[1], timeout=10.0)
    except telegram_client.TelegramError as exc:
        log.warning("telegram_reply_failed", kind=exc.kind)
