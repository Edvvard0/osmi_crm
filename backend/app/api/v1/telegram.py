import hmac
import json
import uuid

from fastapi import APIRouter, Request, Response

from app.api.deps import Client, CurrentUser, Director, SessionDep
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.telegram import (
    Empty,
    LinkCode,
    NotificationSetting,
    NotificationSettingsPatch,
    TelegramStatus,
    TelegramTestResult,
)
from app.services import telegram as svc
from app.services import telegram_bot

router = APIRouter(tags=["telegram"])

MAX_UPDATE_BYTES = 1_000_000


@router.get("/telegram/status", response_model=TelegramStatus)
async def get_status(user: CurrentUser) -> TelegramStatus:
    return svc.status_of(user)


@router.post("/telegram/link-code", response_model=LinkCode, status_code=201)
async def create_link_code(_: Empty, user: CurrentUser, session: SessionDep) -> LinkCode:
    return await svc.create_link_code(session, user)


@router.delete("/telegram/link", status_code=204)
async def unlink(user: CurrentUser, session: SessionDep, client: Client) -> Response:
    await svc.unlink(session, user, client)
    return Response(status_code=204)


@router.get("/telegram/notification-settings", response_model=list[NotificationSetting])
async def get_notification_settings(user: CurrentUser, session: SessionDep) -> list[NotificationSetting]:
    return await svc.list_settings(session, user)


@router.patch("/telegram/notification-settings", response_model=list[NotificationSetting])
async def patch_notification_settings(
    data: NotificationSettingsPatch, user: CurrentUser, session: SessionDep
) -> list[NotificationSetting]:
    return await svc.patch_settings(session, user, data)


@router.post("/telegram/webhook", include_in_schema=False)
async def webhook(request: Request, session: SessionDep) -> dict[str, object]:
    settings = get_settings()
    if not settings.telegram_enabled or settings.telegram_mode != "webhook":
        raise AppError(404, "not_found")
    secret = settings.telegram_webhook_secret
    given = request.headers.get("x-telegram-bot-api-secret-token", "")
    if secret is None or not hmac.compare_digest(
        given.encode(), secret.get_secret_value().encode()
    ):
        raise AppError(403, "forbidden")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPDATE_BYTES:
        raise AppError(413, "payload_too_large")
    body = await request.body()
    if len(body) > MAX_UPDATE_BYTES:
        raise AppError(413, "payload_too_large")
    try:
        update = json.loads(body)
    except ValueError:
        return {}
    if isinstance(update, dict):
        await telegram_bot.handle_update(session, update)
    return {}


@router.post("/locations/{location_id}/telegram-test", response_model=TelegramTestResult)
async def telegram_test(
    location_id: uuid.UUID, _: Empty, actor: Director, session: SessionDep
) -> TelegramTestResult:
    await svc.test_location_chat(session, actor, location_id)
    return TelegramTestResult(sent=True)
