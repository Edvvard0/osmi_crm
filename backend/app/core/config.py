from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
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
    telegram_mode: Literal["webhook", "polling", "off"] = "off"
    telegram_webhook_secret: SecretStr | None = None
    telegram_api_base: str = "https://api.telegram.org"
    public_base_url: str = ""
    app_timezone: str = "Europe/Moscow"

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
    return s
