from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://crm:crm@localhost:5432/crm"
    secret_key: SecretStr = Field(default=SecretStr("dev-only-change-me"))
    max_body_bytes: int = 1_048_576
    client_errors_per_minute: int = 20
    client_error_max_bytes: int = 8_192
    access_ttl_seconds: int = 900
    refresh_ttl_days: int = 14
    login_per_minute: int = 10
    max_failed_logins: int = 5
    lock_minutes: int = 15
    seed_director_password: SecretStr | None = None

    # Модуль 7: Telegram (значения в API не отдаются)
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str = ""
    telegram_mode: Literal["webhook", "polling", "off"] = "off"  # "disabled" — синоним "off"
    telegram_webhook_secret: SecretStr | None = None
    telegram_api_base: str = "https://api.telegram.org"
    public_base_url: str = "http://localhost:5173"
    app_timezone: str = "Europe/Moscow"

    # Модуль 12: эксплуатация (api-contract-m12.md)
    cors_origins: str = ""  # через запятую; только для dev
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    worker_heartbeat_seconds: int = Field(default=30, ge=1)
    ready_worker_max_age_seconds: int = Field(default=120, ge=1)
    ready_outbox_max_age_seconds: int = Field(default=300, ge=1)
    backup_retention_days: int = Field(default=30, ge=1)
    backup_marker_path: str = "/backup/last_success"
    app_version: str = "dev"

    @field_validator(
        "telegram_bot_token", "telegram_webhook_secret", "seed_director_password", mode="before"
    )
    @classmethod
    def _empty_secret_is_none(cls, v: object) -> object:
        """Пустая переменная окружения (`TELEGRAM_WEBHOOK_SECRET=` в compose) = «не задано»:
        пустой секрет вебхука иначе принимал бы запросы без заголовка."""
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("telegram_mode", mode="before")
    @classmethod
    def _telegram_mode_alias(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip().lower()
            return "off" if v in ("disabled", "") else v
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def _log_level_upper(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("app_timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception as exc:
            raise ValueError("APP_TIMEZONE должна быть IANA-зоной, например Europe/Moscow") from exc
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        """Разрешённые CORS-origin: только вне prod (в prod приложение и API с одного origin)."""
        if self.is_prod:
            return []
        items = [self.public_base_url, *self.cors_origins.split(",")]
        seen: list[str] = []
        for raw in items:
            origin = raw.strip().rstrip("/")
            if origin and origin != "*" and origin not in seen:
                seen.append(origin)
        return seen

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_bot_token.get_secret_value())

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_prod and s.secret_key.get_secret_value() == "dev-only-change-me":
        raise RuntimeError("SECRET_KEY must be set in production")
    if s.is_prod and "database_url" not in s.model_fields_set:
        raise RuntimeError("DATABASE_URL must be set in production")
    return s
