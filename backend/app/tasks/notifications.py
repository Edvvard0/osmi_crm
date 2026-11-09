"""Задачи модуля 7: отправка outbox, поиск просроченных заказов, очистка."""

from datetime import time

from app.core.periodic import register, session_scope
from app.services import outbox

MAX_BATCHES_PER_RUN = 20


async def outbox_dispatch() -> None:
    """Отправляет пачки, пока очередь не опустеет (пауза 1 с задаётся интервалом задачи)."""
    for _ in range(MAX_BATCHES_PER_RUN):
        async with session_scope() as session:
            if await outbox.dispatch_once(session) == 0:
                return


async def overdue_scan() -> None:
    async with session_scope() as session:
        await outbox.overdue_scan(session)


async def outbox_cleanup() -> None:
    async with session_scope() as session:
        await outbox.cleanup(session)


register("outbox_dispatch", outbox_dispatch, interval=1)
register("overdue_scan", overdue_scan, interval=300)
register("outbox_cleanup", outbox_cleanup, daily_at=time(3, 30))
