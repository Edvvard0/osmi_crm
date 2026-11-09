import importlib
import pkgutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.api.v1 as api_v1
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def _include_routers(app: FastAPI) -> None:
    """Подключает `router` из каждого модуля пакета app.api.v1 (по алфавиту).

    Новый модуль достаточно положить файлом в app/api/v1 — main.py не меняется.
    """
    for info in sorted(pkgutil.iter_modules(api_v1.__path__), key=lambda i: i.name):
        module = importlib.import_module(f"{api_v1.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router, prefix="/api/v1")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.is_prod)
    docs = None if settings.is_prod else "/api/docs"
    app = FastAPI(
        title="CRM",
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=None if settings.is_prod else "/api/redoc",
        openapi_url=None if settings.is_prod else "/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    _include_routers(app)
    return app


app = create_app()
