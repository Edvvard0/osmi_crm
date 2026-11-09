"""Единый формат ошибок: {"error": {"code","message","fields","request_id"}}.

Внутренние детали (трейсбек, SQL, имена ограничений, введённые значения) клиенту не отдаются.
"""

import re
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.security_headers import security_header_items

log = structlog.get_logger()

HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    502: "service_unavailable",
    503: "service_unavailable",
    504: "service_unavailable",
}
MESSAGES = {
    "bad_request": "Некорректный запрос",
    "unauthorized": "Требуется вход",
    "forbidden": "Нет доступа",
    "not_found": "Не найдено",
    "method_not_allowed": "Метод не поддерживается",
    "conflict": "Конфликт данных",
    "payload_too_large": "Слишком большой запрос",
    "unsupported_media_type": "Неподдерживаемый формат",
    "validation_error": "Проверьте введённые данные",
    "rate_limited": "Слишком много запросов, повторите позже",
    "internal_error": "Внутренняя ошибка сервера",
    "service_unavailable": "Сервис временно недоступен",
    "unique_violation": "Такая запись уже существует",
    "reference_violation": "Связанная запись не найдена или используется",
    "constraint_violation": "Данные нарушают ограничения",
    "invalid_credentials": "Неверный логин или пароль",
    "account_locked": "Учётная запись временно заблокирована. Повторите попытку позже",
    "invalid_token": "Сессия недействительна, войдите заново",
    "invalid_current_password": "Неверный текущий пароль",
    "duplicate_phone": "Клиент с таким телефоном уже существует",
    "duplicate_vin": "Автомобиль с таким VIN уже существует",
    "client_archived": "Клиент в архиве",
    "post_busy": "Пост занят",
    "outside_working_hours": "Запись должна укладываться в рабочие часы точки в пределах суток",
    "invalid_transition": "Недопустимая смена статуса записи",
    "invalid_state": "Запись в этом статусе изменить нельзя",
    "telegram_disabled": "Telegram не настроен",
    "already_linked": "Аккаунт уже привязан к Telegram",
    "telegram_unavailable": "Telegram недоступен, повторите позже",
    "insufficient_stock": "Недостаточно товара на складе",
    "stock_changed": "Остатки изменились, обновите страницу",
    "already_reversed": "Движение уже сторнировано",
    "another_task_active": "У вас уже есть работа в исполнении",
    "order_not_workable": "Заказ ещё не передан в работу",
    "version_conflict": "Данные изменились, обновите страницу",
    "order_empty": "В заказе нет работ",
    "items_not_done": "Не все работы выполнены",
    "item_started": "Работа уже начата, изменить её нельзя",
    "item_active": "Работа выполняется, смена механика невозможна",
    "appointment_has_order": "По записи уже создан заказ-наряд",
    "overpayment": "Сумма оплаты превышает остаток к оплате",
    "nothing_to_pay": "Заказ уже оплачен полностью",
    "refund_exceeds_payment": "Сумма возврата превышает доступную к возврату",
    "order_not_paid": "Заказ не оплачен полностью",
    "has_payments": "По заказу есть оплаты — сначала оформите возврат",
    "total_below_paid": "Итог заказа не может быть меньше уже оплаченной суммы",
    "scheme_overlap": "Для этого сотрудника на выбранные даты уже действует схема",
}


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        fields: dict[str, str] | None = None,
        details: dict[str, str] | None = None,
    ) -> None:
        self.status, self.code, self.fields = status, code, fields or {}
        self.details = details


def error_response(
    status: int,
    code: str,
    request: Request,
    fields: dict[str, str] | None = None,
    details: dict[str, str] | None = None,
) -> JSONResponse:
    rid = getattr(request.state, "request_id", None)
    error: dict[str, object] = {
        "code": code,
        "message": MESSAGES.get(code, MESSAGES["internal_error"]),
        "fields": fields or {},
        "request_id": rid,
    }
    if details:
        # Только безопасные идентификаторы/имя существующей записи (без SQL и внутренних деталей).
        error["details"] = details
    body = {"error": error}
    resp = JSONResponse(body, status_code=status)
    # Ответы ServerErrorMiddleware (500) идут мимо SecurityHeadersMiddleware.
    for name, value in security_header_items(request.url.path, get_settings().hsts):
        resp.headers.setdefault(name, value)
    if rid:
        resp.headers["X-Request-ID"] = rid
    return resp


_REASON_CODE = re.compile(r"^[a-z][a-z_]{2,39}$")


def _field_code(e: Any) -> str:
    """Тип ошибки поля. Для собственных валидаторов (ValueError("код")) — сам код, например
    markup_not_allowed: это строка из нашего кода, а не введённое значение."""
    kind = str(e["type"])
    if kind == "value_error":
        reason = str((e.get("ctx") or {}).get("error", ""))
        if _REASON_CODE.fullmatch(reason):
            return reason
    return kind


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, request, exc.fields, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        default = "internal_error" if exc.status_code >= 500 else "bad_request"
        return error_response(exc.status_code, HTTP_CODES.get(exc.status_code, default), request)

    @app.exception_handler(RequestValidationError)
    async def _val(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Только путь к полю и тип ошибки; введённые значения (input/ctx/msg) не возвращаем.
        fields: dict[str, str] = {}
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path"))
            fields[loc or "_"] = _field_code(e)
        return error_response(422, "validation_error", request, fields)

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        pgcode = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        log.warning("db_integrity_error", pgcode=pgcode, path=request.url.path)
        code = {"23505": "unique_violation", "23503": "reference_violation"}.get(
            str(pgcode), "constraint_violation"
        )
        return error_response(409, code, request)

    @app.exception_handler(DBAPIError)
    async def _dbapi(request: Request, exc: DBAPIError) -> JSONResponse:
        log.error("db_error", path=request.url.path, exc_info=exc)
        return error_response(500, "internal_error", request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", path=request.url.path, exc_info=exc)
        return error_response(500, "internal_error", request)
