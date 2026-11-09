import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import field_validator, model_validator

from app.schemas.audit import UserRef
from app.schemas.common import Strict

_PERCENT = re.compile(r"^\d{1,3}(\.\d{1,2})?$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Heatmap(Strict):
    hours: list[float | int]
    actions: list[int]


class SettingsRead(Strict):
    discount_alert_percent: str
    daily_summary_time: str | None
    session_retention_days: int
    heatmap_thresholds: Heatmap
    updated_at: datetime | None
    updated_by: UserRef | None


def _bad() -> ValueError:
    return ValueError("invalid_value")


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _triple_increasing(values: list[Any]) -> bool:
    return all(a < b for a, b in zip(values, values[1:], strict=False))


class SettingsPatch(Strict):
    """Любое подмножество ключей; ошибки значений привязаны к имени ключа (`fields.<ключ>`)."""

    discount_alert_percent: Any = None
    daily_summary_time: Any = None
    session_retention_days: Any = None
    heatmap_thresholds: Any = None

    @model_validator(mode="after")
    def _not_empty(self) -> "SettingsPatch":
        if not self.model_fields_set:
            raise ValueError("empty_patch")
        return self

    @field_validator("discount_alert_percent", mode="before")
    @classmethod
    def _percent(cls, v: Any) -> str:
        if not isinstance(v, str) or not _PERCENT.fullmatch(v):
            raise _bad()
        try:
            d = Decimal(v)
        except InvalidOperation:
            raise _bad() from None
        if not Decimal(1) <= d <= Decimal(100):
            raise _bad()
        return f"{d:.2f}"

    @field_validator("daily_summary_time", mode="before")
    @classmethod
    def _time(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or not _HHMM.fullmatch(v):
            raise _bad()
        return v

    @field_validator("session_retention_days", mode="before")
    @classmethod
    def _days(cls, v: Any) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or not 7 <= v <= 365:
            raise _bad()
        return v

    @field_validator("heatmap_thresholds", mode="before")
    @classmethod
    def _heatmap(cls, v: Any) -> dict[str, list[float | int]]:
        if not isinstance(v, dict) or set(v) != {"hours", "actions"}:
            raise _bad()
        hours, actions = v["hours"], v["actions"]
        if not (isinstance(hours, list) and isinstance(actions, list)):
            raise _bad()
        if len(hours) != 3 or len(actions) != 3:
            raise _bad()
        if not all(_is_num(h) and 0.5 <= h <= 24 and (h * 2) == int(h * 2) for h in hours):
            raise _bad()
        if not all(
            isinstance(a, int) and not isinstance(a, bool) and 1 <= a <= 1000 for a in actions
        ):
            raise _bad()
        if not (_triple_increasing(hours) and _triple_increasing(actions)):
            raise _bad()
        return {
            "hours": [int(h) if float(h).is_integer() else float(h) for h in hours],
            "actions": list(actions),
        }
