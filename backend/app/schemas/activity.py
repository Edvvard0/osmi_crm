"""Схемы модуля 10: тепловая карта активности и детализация дня."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.audit import UserRef
from app.schemas.common import Strict
from app.schemas.payroll import PayrollOrderRef

ActivityKind = Literal["hours", "actions"]


class ActivityDay(Strict):
    date: date
    minutes: int | None
    hours: str | None
    actions: int | None
    works_count: int
    level: Literal[0, 1, 2, 3, 4]
    order_numbers: list[str]


class ActivitySummary(Strict):
    working_days: int
    total_hours: str | None
    total_actions: int | None
    average_per_working_day: str
    longest_streak_days: int


class ActivityHeatmap(Strict):
    user: UserRef
    kind: ActivityKind
    from_: date = Field(alias="from")
    to: date
    timezone: str
    first_day: date
    thresholds: list[int | float]
    days: list[ActivityDay]
    summary: ActivitySummary

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class HoursEntry(Strict):
    order: PayrollOrderRef
    plate_number: str | None
    item_id: uuid.UUID
    item_name: str
    started_at: datetime
    ended_at: datetime | None
    minutes: int


class ActionEntry(Strict):
    at: datetime
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    label: str
    order_number: str | None


class ActivityDetailsDay(Strict):
    date: date
    total_minutes: int | None
    actions: int | None
    truncated: bool
    entries: list[HoursEntry] | list[ActionEntry]


class ActivityDetails(Strict):
    user: UserRef
    kind: ActivityKind
    days: list[ActivityDetailsDay]
