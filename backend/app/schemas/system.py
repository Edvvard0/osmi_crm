"""Схемы health/ready и GET /system/status (api-contract-m12.md)."""

from datetime import datetime
from typing import Literal

from app.schemas.common import Strict


class CheckDb(Strict):
    ok: bool


class CheckMigrations(Strict):
    ok: bool
    current: str | None
    head: str


class CheckWorker(Strict):
    ok: bool
    heartbeat_age_seconds: int | None


class CheckOutbox(Strict):
    ok: bool
    pending: int
    oldest_pending_age_seconds: int | None


class ReadyChecks(Strict):
    db: CheckDb
    migrations: CheckMigrations
    worker: CheckWorker
    outbox: CheckOutbox


class Ready(Strict):
    status: Literal["ok", "degraded", "down"]
    checks: ReadyChecks


class StatusMigrations(Strict):
    current: str | None
    head: str


class StatusWorker(Strict):
    last_heartbeat_at: datetime | None
    ok: bool


class StatusOutbox(Strict):
    pending: int
    failed_24h: int
    oldest_pending_age_seconds: int | None


class StatusTelegram(Strict):
    mode: Literal["disabled", "polling", "webhook"]
    bot_username: str | None


class SystemStatus(Strict):
    server_time: datetime
    app_timezone: str
    env: Literal["prod", "dev", "test"]
    migrations: StatusMigrations
    worker: StatusWorker
    outbox: StatusOutbox
    telegram: StatusTelegram
    last_backup_at: datetime | None
    version: str
