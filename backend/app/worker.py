"""Воркер: `python -m app.worker` — asyncio-цикл реестра периодических задач.

Задачи регистрируют модули пакета `app.tasks`; каждая идёт под PostgreSQL advisory lock,
поэтому несколько экземпляров воркера не дублируют работу.
"""

import argparse
import asyncio
import importlib
import pkgutil
import signal
import sys

import structlog

from app import tasks as tasks_pkg
from app.core import periodic
from app.core.db import dispose_engine
from app.services import telegram_client

log = structlog.get_logger()


def load_tasks() -> list[str]:
    """Импортирует все модули `app.tasks.*`; возвращает имена зарегистрированных задач."""
    for mod in pkgutil.iter_modules(tasks_pkg.__path__):
        importlib.import_module(f"{tasks_pkg.__name__}.{mod.name}")
    return sorted(periodic.REGISTRY)


async def run(stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows / не главный поток
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    names = load_tasks()
    log.info("worker_started", tasks=names)
    try:
        await periodic.run_all(stop)
    finally:
        await telegram_client.close_client()
        await dispose_engine()
        log.info("worker_stopped")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument("--healthcheck", action="store_true", help="проверка для контейнера")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return asyncio.run(_healthcheck())
    asyncio.run(run())
    return 0


async def _healthcheck() -> int:  # pragma: no cover
    """Минимальная проверка: БД отвечает. Проверку heartbeat добавляет модуль 12."""
    from sqlalchemy import text

    from app.core.db import get_engine

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return 1
    finally:
        await dispose_engine()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
