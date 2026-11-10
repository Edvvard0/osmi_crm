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
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.logging import setup_logging
from app.services import telegram_client

log = structlog.get_logger()


def load_tasks() -> list[str]:
    """Импортирует все модули `app.tasks.*`; возвращает имена зарегистрированных задач."""
    for mod in pkgutil.iter_modules(tasks_pkg.__path__):
        # Имя модуля берётся из списка файлов пакета (pkgutil), не из ввода пользователя.
        importlib.import_module(f"{tasks_pkg.__name__}.{mod.name}")  # nosemgrep
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
    settings = get_settings()
    setup_logging(settings.is_prod, settings.log_level)
    asyncio.run(run())
    return 0


async def _healthcheck() -> int:  # pragma: no cover
    """0 — heartbeat воркера свежий (не старше READY_WORKER_MAX_AGE_SECONDS)."""
    from app.core.periodic import session_scope
    from app.services import system_status

    try:
        async with session_scope() as session:
            fresh = await system_status.heartbeat_is_fresh(session)
    except Exception:
        return 1
    finally:
        await dispose_engine()
    return 0 if fresh else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
