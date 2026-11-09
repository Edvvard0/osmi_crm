import json
import re
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class RequestContextMiddleware:
    """request-id, лимит размера тела, структурный лог, чистые заголовки ответа."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        headers = dict(scope["headers"])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _RID.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)

        declared = headers.get(b"content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_body_bytes:
            await self._too_large(send, rid)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > settings.max_body_bytes:
                    raise _BodyTooLarge
            return msg

        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                hdrs = [
                    (k, v)
                    for k, v in message["headers"]
                    if k.lower() not in (b"server", b"x-powered-by", b"x-request-id")
                ]
                hdrs.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": hdrs}
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _BodyTooLarge:
            if not started:
                await self._too_large(send, rid)
        structlog.get_logger().info("request", method=scope["method"], path=scope["path"])

    @staticmethod
    async def _too_large(send: Send, rid: str) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": "Слишком большой запрос",
                    "fields": {},
                    "request_id": rid,
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", rid.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass
