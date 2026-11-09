import re
import uuid
from functools import lru_cache
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import AfterValidator, BeforeValidator, Field

from app.core.types import Phone, SafeText, _must_be_str
from app.schemas.common import PatchBase, Strict

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@lru_cache(maxsize=1)
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def _timezone(v: str) -> str:
    if v not in _timezones():
        raise ValueError("invalid_timezone")
    return v


def _hhmm(v: str) -> str:
    if not _HHMM.fullmatch(v):
        raise ValueError("invalid_time")
    return v


# IANA-пояс (например, Europe/Moscow) и время "HH:MM" — строгие белые списки.
Timezone = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_timezone)]
WorkTime = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_hhmm)]


# Идентификатор чата Telegram: целое со знаком int64 (у групп отрицательный), без приведения типов.
TelegramChatId = Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)]


class LocationCreate(Strict):
    name: SafeText(100, 1)  # type: ignore[valid-type]
    address: SafeText(255, 1)  # type: ignore[valid-type]
    phone: Phone | None = None
    timezone: Timezone = "Europe/Moscow"
    work_start: WorkTime = "09:00"
    work_end: WorkTime = "21:00"


class LocationUpdate(PatchBase):
    nullable_fields = frozenset({"phone", "telegram_chat_id"})

    name: SafeText(100, 1) | None = None  # type: ignore[valid-type]
    address: SafeText(255, 1) | None = None  # type: ignore[valid-type]
    phone: Phone | None = None
    is_active: bool | None = None
    timezone: Timezone | None = None
    work_start: WorkTime | None = None
    work_end: WorkTime | None = None
    telegram_chat_id: TelegramChatId | None = None


class LocationRead(Strict):
    id: uuid.UUID
    name: str
    address: str
    phone: str | None
    is_active: bool
    code: str
    timezone: str
    work_start: str
    work_end: str
    has_telegram_chat: bool = False
    # Значение видит только руководитель, остальным null.
    telegram_chat_id: int | None = None
