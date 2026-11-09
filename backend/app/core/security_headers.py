"""Заголовки безопасности ответов API (api-contract-m12.md).

Основные заголовки ставит edge (nginx) на каждый ответ; API дублирует их для прямого доступа
и всегда ставит `X-Content-Type-Options` и `Cache-Control: no-store` на `/api/v1/**` (кроме
`/health*`). Уже выставленные приложением заголовки не перезаписываются.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

_DOC_PATHS = ("/api/docs", "/api/redoc", "/openapi.json")
_HSTS = "max-age=63072000; includeSubDomains"
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def security_header_items(path: str, prod: bool) -> list[tuple[str, str]]:
    """Заголовки безопасности для ответа на `path` (имена в нижнем регистре)."""
    items = [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "same-origin"),
        ("permissions-policy", "camera=(), microphone=(), geolocation=()"),
    ]
    if path not in _DOC_PATHS:  # Swagger UI в dev грузит скрипты и стили с CDN
        items.append(("content-security-policy", _API_CSP))
    if prod:
        items.append(("strict-transport-security", _HSTS))
    if path.startswith("/api/v1/") and not path.startswith("/api/v1/health"):
        items.append(("cache-control", "no-store"))
    return items


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        prod = get_settings().is_prod
        path = str(scope.get("path", ""))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for name, value in security_header_items(path, prod):
                    if name.encode() not in present:
                        headers.append((name.encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
