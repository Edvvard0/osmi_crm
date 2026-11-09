from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import auth, client_errors, health, locations, users
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


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
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(client_errors.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(locations.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    return app


app = create_app()
