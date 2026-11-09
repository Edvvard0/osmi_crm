"""Служебные задачи: очистка устаревших refresh-сессий (модуль 11)."""

from datetime import time

from app.core.periodic import register, session_scope
from app.services import user_sessions


async def session_cleanup() -> None:
    async with session_scope() as session:
        await user_sessions.session_cleanup(session)
        await session.commit()


register("session_cleanup", session_cleanup, daily_at=time(3, 45))
