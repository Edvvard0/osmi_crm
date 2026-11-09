"""Бот в режиме polling (dev): `python -m app.bot`. В webhook-режиме не нужен."""

import asyncio
import signal
import sys

import structlog

from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.periodic import session_scope
from app.services import telegram_bot, telegram_client

log = structlog.get_logger()


async def poll(stop: asyncio.Event, max_iterations: int | None = None) -> None:
    client = telegram_client.get_client()
    if client is None:
        log.info("bot_disabled")
        return
    await client.delete_webhook()  # getUpdates не работает при установленном вебхуке
    offset: int | None = None
    n = 0
    while not stop.is_set() and (max_iterations is None or n < max_iterations):
        n += 1
        try:
            updates = await client.get_updates(offset)
        except telegram_client.TelegramError as exc:
            log.warning("bot_poll_failed", kind=exc.kind)
            await asyncio.sleep(3)
            continue
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            async with session_scope() as session:
                await telegram_bot.handle_update(session, update)


async def run() -> None:  # pragma: no cover
    if get_settings().telegram_mode != "polling":
        log.info("bot_not_polling_mode")
        return
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await poll(stop)
    finally:
        await telegram_client.close_client()
        await dispose_engine()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(run())
    sys.exit(0)
