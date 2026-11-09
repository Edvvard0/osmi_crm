"""Ежедневная сводка директору: проверка раз в минуту (модуль 10)."""

from app.core.periodic import register, session_scope
from app.services import daily_summary


async def daily_summary_task() -> None:
    async with session_scope() as session:
        if await daily_summary.run_once(session):
            await session.commit()


register("daily_summary", daily_summary_task, interval=60)
