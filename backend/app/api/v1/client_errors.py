"""Приём ошибок фронтенда: только запись в лог, ничего не возвращаем."""

import time
from collections import defaultdict, deque

import structlog
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.types import SafeText

router = APIRouter(tags=["client-errors"])
log = structlog.get_logger()
_hits: dict[str, deque[float]] = defaultdict(deque)


class ClientError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: SafeText(500)  # type: ignore[valid-type]
    stack: SafeText(4000) | None = None  # type: ignore[valid-type]
    url: SafeText(500) | None = None  # type: ignore[valid-type]
    kind: SafeText(32) | None = None  # type: ignore[valid-type]


def _allow(ip: str) -> bool:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= get_settings().client_errors_per_minute:
        return False
    q.append(now)
    return True


@router.post("/client-errors", status_code=204)
async def client_errors(payload: ClientError, request: Request) -> Response:
    ip = request.client.host if request.client else "unknown"
    if not _allow(ip):
        raise AppError(429, "rate_limited")
    if len(payload.model_dump_json()) > get_settings().client_error_max_bytes:
        raise AppError(413, "payload_too_large")
    log.warning("client_error", **payload.model_dump(exclude_none=True))
    return Response(status_code=204)
