import os

os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://crm:crm@localhost:5432/crm_test")

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.main import create_app


def build_app(env: str = "test") -> FastAPI:
    os.environ["ENV"] = env
    if env == "prod":
        os.environ["SECRET_KEY"] = "x" * 40
    get_settings.cache_clear()
    app = create_app()

    @app.get("/_boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail: password=hunter2")

    @app.get("/_integrity")
    async def integrity() -> None:
        class Orig(Exception):
            sqlstate = "23505"

        raise IntegrityError(
            "INSERT INTO customers ...",
            {},
            Orig('duplicate key value violates "uq_customers_phone"'),
        )

    @app.post("/_echo")
    async def echo(data: dict[str, int]) -> dict[str, int]:
        return data

    return app


@pytest.fixture
async def client():
    app = build_app("test")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
async def prod_client():
    app = build_app("prod")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    os.environ["ENV"] = "test"
    os.environ.pop("SECRET_KEY", None)
    get_settings.cache_clear()


# ---------- интеграционные фикстуры (PostgreSQL, откат в конце каждого теста) ----------
from collections.abc import AsyncIterator  # noqa: E402

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,  # noqa: E402
)

from app.core.db import get_session  # noqa: E402
from app.core.ratelimit import login_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    login_limiter.reset()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(get_settings().database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def conn(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as connection:
        trans = await connection.begin()
        yield connection
        await trans.rollback()


@pytest.fixture
async def db(conn: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Сессия тестовых фабрик; commit внутри — это SAVEPOINT, всё откатывается в конце теста."""
    async with AsyncSession(
        conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session


def make_api_client(conn: AsyncConnection, ip: str = "203.0.113.5") -> httpx.AsyncClient:
    app = build_app("test")

    async def override() -> AsyncIterator[AsyncSession]:
        # Новая сессия на каждый запрос, как в проде, но на общем соединении теста.
        async with AsyncSession(
            conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session

    app.dependency_overrides[get_session] = override
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(ip, 50000))
    # https: cookie refresh_token помечена Secure, по http httpx её бы не вернул.
    return httpx.AsyncClient(transport=transport, base_url="https://t")


@pytest.fixture
async def api(conn: AsyncConnection) -> AsyncIterator[httpx.AsyncClient]:
    async with make_api_client(conn) as c:
        yield c
    get_settings.cache_clear()
