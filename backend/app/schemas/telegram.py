from datetime import datetime

from pydantic import Field

from app.schemas.common import Strict


class TelegramStatus(Strict):
    enabled: bool
    bot_username: str | None
    linked: bool
    telegram_username: str | None


class LinkCode(Strict):
    code: str
    link: str
    expires_at: datetime


class NotificationSetting(Strict):
    event_type: str
    title: str
    description: str
    is_enabled: bool
    is_default: bool


class NotificationSettingItem(Strict):
    event_type: str = Field(min_length=1, max_length=50)
    is_enabled: bool


class NotificationSettingsPatch(Strict):
    items: list[NotificationSettingItem] = Field(min_length=1, max_length=50)


class Empty(Strict):
    """Пустое тело `{}`."""


class TelegramTestResult(Strict):
    sent: bool
