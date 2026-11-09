"""Heartbeat воркера: `system_settings['_worker_heartbeat']` (модуль 12)."""

from app.core.config import get_settings
from app.core.periodic import register, session_scope
from app.services import system_status


async def heartbeat() -> None:
    async with session_scope() as session:
        await system_status.write_heartbeat(session)
        await session.commit()


register("heartbeat", heartbeat, interval=float(get_settings().worker_heartbeat_seconds))
