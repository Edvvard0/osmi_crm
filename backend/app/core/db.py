from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _maker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    get_engine()
    assert _maker is not None
    async with _maker() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _maker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _maker = None
