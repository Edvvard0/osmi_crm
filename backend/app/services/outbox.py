"""Отправка notification_outbox, очистка и поиск просроченных заказов (api-contract-m7.md)."""

import asyncio
import time as _time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import structlog
from sqlalchemy import bindparam, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import BigInteger

from app.models import Location, User
from app.models.telegram import NotificationOutbox
from app.services import telegram_client
from app.services.audit import write_audit
from app.services.events import publish
from app.services.sessions import utcnow

log = structlog.get_logger()

BATCH = 30
MAX_ATTEMPTS = 5
BACKOFF_BASE = 30  # секунд; задержка = 30 * 2^(attempts - 1)
GLOBAL_PER_SECOND = 30
CHAT_INTERVAL = 1.0  # на личный чат — не чаще 1 в секунду
GROUP_INTERVAL = 3.0  # на группу — не чаще 20 в минуту
RETENTION_DAYS = 30
SEND_TIMEOUT = 10.0


class Throttle:
    """Ограничения скорости отправки; часы и пауза подменяются в тестах."""

    def __init__(
        self,
        clock: Callable[[], float] = _time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._next_chat: dict[int, float] = {}
        self._next_global = 0.0

    def cooling(self) -> list[int]:
        """Чаты, в которые пока писать нельзя."""
        now = self._clock()
        for chat_id in [c for c, t in self._next_chat.items() if t <= now]:
            del self._next_chat[chat_id]
        return list(self._next_chat)

    def hold(self, chat_id: int, seconds: float) -> None:
        self._next_chat[chat_id] = max(self._next_chat.get(chat_id, 0.0), self._clock() + seconds)

    def mark_sent(self, chat_id: int) -> None:
        self.hold(chat_id, GROUP_INTERVAL if chat_id < 0 else CHAT_INTERVAL)

    async def wait_global(self) -> None:
        now = self._clock()
        slot = max(now, self._next_global)
        self._next_global = slot + 1.0 / GLOBAL_PER_SECOND
        if slot > now:
            await self._sleep(slot - now)


_default_throttle = Throttle()


def backoff_seconds(attempts: int) -> int:
    return BACKOFF_BASE * (1 << max(attempts - 1, 0))


_PICK = text(
    """
    SELECT id FROM (
        SELECT DISTINCT ON (o.chat_id) o.id, o.chat_id
        FROM notification_outbox o
        WHERE o.status = 'pending' AND o.next_attempt_at <= now()
          AND o.chat_id <> ALL(:cooling)
          AND NOT EXISTS (
              SELECT 1 FROM notification_outbox p
              WHERE p.chat_id = o.chat_id AND p.status = 'pending'
                AND p.id < o.id AND p.next_attempt_at > now())
        ORDER BY o.chat_id, o.id
    ) t ORDER BY id LIMIT :lim
    """
).bindparams(bindparam("cooling", type_=ARRAY(BigInteger())))


async def _disable_chat(session: AsyncSession, row: NotificationOutbox) -> None:
    """Бот заблокирован/чат не найден: чат очищается, остальные pending этого чата пропускаются."""
    chat_id = row.chat_id
    if row.user_id is not None:
        user = await session.get(User, row.user_id, with_for_update=True)
        if user is not None and user.telegram_chat_id == chat_id:
            user.telegram_chat_id = None
            user.telegram_username = None
            write_audit(
                session,
                action="update",
                entity_type="user",
                user_id=None,
                entity_id=user.id,
                changes={"telegram_linked": {"old": True, "new": False}},
            )
    else:
        locations = await session.scalars(
            select(Location).where(Location.telegram_chat_id == chat_id).with_for_update()
        )
        for loc in locations:
            loc.telegram_chat_id = None
            write_audit(
                session,
                action="update",
                entity_type="location",
                user_id=None,
                entity_id=loc.id,
                location_id=loc.id,
                changes={"telegram_chat_id": {"old": "set", "new": None}},
            )
    await session.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.chat_id == chat_id, NotificationOutbox.status == "pending")
        .values(status="skipped", last_error="blocked")
    )


def _fail_or_retry(row: NotificationOutbox, err: telegram_client.TelegramError) -> None:
    row.attempts = (row.attempts or 0) + 1
    row.last_error = f"{err.kind}: {err.description}"[:500]
    if err.kind == "permanent" or row.attempts >= MAX_ATTEMPTS:
        row.status = "failed"
        return
    delay = float(backoff_seconds(row.attempts))
    if err.kind == "rate_limit" and err.retry_after is not None:
        delay = max(delay, float(err.retry_after))
    row.next_attempt_at = utcnow() + timedelta(seconds=delay)


async def dispatch_once(
    session: AsyncSession,
    client: telegram_client.TelegramClient | None = None,
    throttle: Throttle | None = None,
) -> int:
    """Одна пачка отправки (до 30 сообщений). Возвращает число обработанных строк."""
    client = client or telegram_client.get_client()
    if client is None:
        return 0
    throttle = throttle or _default_throttle
    ids = (
        await session.scalars(_PICK, {"cooling": throttle.cooling(), "lim": BATCH})
    ).all()
    await session.commit()  # завершаем читающую транзакцию, дальше — по строке
    done = 0
    for row_id in ids:
        # Условия выборки повторяются под блокировкой: между _PICK и FOR UPDATE строку мог
        # обработать другой воркер (отправить или отложить ретраем) — второй отправки не будет.
        row = await session.scalar(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.id == row_id,
                NotificationOutbox.status == "pending",
                NotificationOutbox.next_attempt_at <= func.now(),
            )
            .with_for_update(skip_locked=True)
        )
        if row is None:  # уже обработана или отложена (отвязка, другой воркер)
            await session.commit()
            continue
        await throttle.wait_global()
        try:
            await client.send_message(row.chat_id, row.text, timeout=SEND_TIMEOUT)
        except telegram_client.TelegramError as err:
            if err.kind == "blocked":
                row.status = "skipped"
                row.last_error = "blocked"
                await _disable_chat(session, row)
            else:
                _fail_or_retry(row, err)
                if err.kind == "rate_limit" and err.retry_after:
                    throttle.hold(row.chat_id, float(err.retry_after))
            log.warning("outbox_send_failed", id=row.id, kind=err.kind, attempts=row.attempts)
        else:
            row.status = "sent"
            row.sent_at = utcnow()
            row.last_error = None
            throttle.mark_sent(row.chat_id)
        await session.commit()
        done += 1
    return done


async def cleanup(session: AsyncSession, now: datetime | None = None) -> int:
    """Удаляет sent/skipped/failed старше 30 дней."""
    border = (now or utcnow()) - timedelta(days=RETENTION_DAYS)
    result = await session.execute(
        delete(NotificationOutbox).where(
            NotificationOutbox.status.in_(("sent", "skipped", "failed")),
            NotificationOutbox.created_at < border,
        )
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


_OVERDUE = text(
    """
    SELECT o.id, o.number, o.location_id, o.planned_ready_at, o.status, v.plate_number
    FROM work_orders o JOIN vehicles v ON v.id = o.vehicle_id
    WHERE o.planned_ready_at < now() AND o.planned_ready_at > now() - interval '14 days'
      AND o.status NOT IN ('ready', 'closed', 'cancelled')
    ORDER BY o.planned_ready_at LIMIT 200
    """
)


async def overdue_scan(session: AsyncSession) -> int:
    """Публикует `work_order.overdue` по просроченным заказам; повторы гасит dedup_key."""
    rows = (await session.execute(_OVERDUE)).all()
    for order_id, number, location_id, planned, status, plate in rows:
        await publish(
            session,
            "work_order.overdue",
            {
                "order_id": str(order_id),
                "order_number": number,
                "plate_number": plate,
                "planned_ready_at": planned.isoformat(),
                "status": status,
            },
            location_id=location_id,
            actor_id=None,
            dedup_key=f"work_order.overdue:{order_id}:{int(planned.timestamp())}",
        )
    await session.commit()
    return len(rows)
