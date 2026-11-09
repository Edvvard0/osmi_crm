"""Клиент Telegram Bot API на httpx с подменяемым транспортом (в тестах — fake, без сети).

Токен берётся только из настроек окружения и никогда не попадает в тексты ошибок и логи.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

import httpx
import structlog

from app.core.config import get_settings

log = structlog.get_logger()

_TOKEN_IN_URL = re.compile(r"/bot[^/\s\"']+")


class _RedactBotToken(logging.Filter):
    """httpx пишет в лог INFO «HTTP Request: POST <url>», а URL Bot API содержит токен."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "/bot" in message:
            record.msg, record.args = _TOKEN_IN_URL.sub("/bot***", message), None
        return True


_httpx_log = logging.getLogger("httpx")
if not any(isinstance(f, _RedactBotToken) for f in _httpx_log.filters):
    _httpx_log.addFilter(_RedactBotToken())

ErrorKind = Literal["blocked", "rate_limit", "temporary", "permanent"]

_override_transport: httpx.AsyncBaseTransport | None = None
_cached: TelegramClient | None = None


class TelegramError(Exception):
    """Ошибка Bot API. `description` не содержит токена и данных запроса."""

    def __init__(self, kind: ErrorKind, description: str = "", retry_after: int | None = None):
        super().__init__(kind)
        self.kind: ErrorKind = kind
        self.description = description[:300]
        self.retry_after = retry_after


def classify(status: int, body: dict[str, Any] | None) -> TelegramError:
    body = body or {}
    description = str(body.get("description") or f"http {status}")
    params = body.get("parameters") or {}
    if status == 429:
        retry = params.get("retry_after")
        return TelegramError(
            "rate_limit", description, int(retry) if isinstance(retry, int | float) else None
        )
    if status == 403 or (status == 400 and "chat not found" in description.lower()):
        return TelegramError("blocked", description)
    if status >= 500:
        return TelegramError("temporary", description)
    return TelegramError("permanent", description)


class TelegramClient:
    def __init__(
        self,
        token: str,
        api_base: str = "https://api.telegram.org",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._base = api_base.rstrip("/")
        self._timeout = timeout
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,  # noqa: ASYNC109 - таймаут запроса httpx, не asyncio
    ) -> Any:
        url = f"{self._base}/bot{self._token}/{method}"
        try:
            resp = await self._http.post(url, json=payload, timeout=timeout or self._timeout)
        except httpx.HTTPError as exc:
            # Текст исключения httpx может содержать URL с токеном — не пробрасываем.
            raise TelegramError("temporary", type(exc).__name__) from None
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code != 200 or not isinstance(body, dict) or not body.get("ok"):
            raise classify(resp.status_code, body if isinstance(body, dict) else None)
        return body.get("result")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        timeout: float | None = None,  # noqa: ASYNC109 - таймаут запроса httpx, не asyncio
    ) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        await self.call("sendMessage", payload, timeout=timeout)

    async def get_updates(self, offset: int | None, poll_timeout: int = 25) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": poll_timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = await self.call("getUpdates", payload, timeout=poll_timeout + 10)
        return result if isinstance(result, list) else []

    async def set_webhook(self, url: str, secret: str) -> None:
        await self.call(
            "setWebhook",
            {"url": url, "secret_token": secret, "allowed_updates": ["message"]},
        )

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", {})

    async def aclose(self) -> None:
        await self._http.aclose()


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Подмена транспорта (тесты). Сбрасывает закэшированный клиент."""
    global _override_transport, _cached
    _override_transport = transport
    _cached = None


def get_client() -> TelegramClient | None:
    """Клиент по текущим настройкам или None, если Telegram выключен (нет токена)."""
    global _cached
    settings = get_settings()
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        return None
    token = settings.telegram_bot_token.get_secret_value()
    if _cached is None or _cached._token != token or _cached._base != settings.telegram_api_base:
        _cached = TelegramClient(
            token, settings.telegram_api_base, transport=_override_transport
        )
    return _cached


async def close_client() -> None:
    global _cached
    if _cached is not None:
        await _cached.aclose()
        _cached = None
