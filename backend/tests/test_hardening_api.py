"""Модуль 12: health/ready, system/status, heartbeat воркера, заголовки безопасности, CORS."""

# ruff: noqa: E501

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import worker
from app.core.config import Settings, get_settings
from app.models import Role
from app.models.system_settings import SystemSetting
from app.models.telegram import NotificationOutbox
from app.services import system_status as svc
from tests.conftest import build_app
from tests.factories import bearer, login, make_location, make_user

API = "/api/v1"
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    svc.reset_ready_cache()
    yield
    svc.reset_ready_cache()
    get_settings.cache_clear()


def use_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


async def ready(api: httpx.AsyncClient) -> httpx.Response:
    svc.reset_ready_cache()
    return await api.get(f"{API}/health/ready")


# ---------- GET /health/ready ----------


async def test_ready_is_public_and_ok_when_telegram_off(api: httpx.AsyncClient) -> None:
    r = await ready(api)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == {"ok": True}
    assert body["checks"]["migrations"] == {"ok": True, "current": "0012", "head": "0012"}
    assert body["checks"]["outbox"]["ok"] is True
    # Нет строк подключения и внутренних деталей.
    assert "postgresql" not in r.text and "crm_test" not in r.text


async def test_ready_worker_missing_is_degraded_when_telegram_on(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_env(monkeypatch, TELEGRAM_MODE="polling")
    r = await ready(api)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["worker"] == {"ok": False, "heartbeat_age_seconds": None}


async def test_ready_worker_fresh_and_stale(
    api: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_env(monkeypatch, TELEGRAM_MODE="polling")
    await svc.write_heartbeat(db)
    await db.commit()
    body = (await ready(api)).json()
    assert body["status"] == "ok"
    assert body["checks"]["worker"]["ok"] is True
    assert 0 <= body["checks"]["worker"]["heartbeat_age_seconds"] < 10

    await svc.write_heartbeat(db, datetime.now(UTC) - timedelta(seconds=500))
    await db.commit()
    r = await ready(api)
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["checks"]["worker"]["ok"] is False
    assert r.json()["checks"]["worker"]["heartbeat_age_seconds"] >= 500


async def test_ready_worker_ignored_when_telegram_off(
    api: httpx.AsyncClient, db: AsyncSession
) -> None:
    await svc.write_heartbeat(db, datetime.now(UTC) - timedelta(seconds=500))
    await db.commit()
    body = (await ready(api)).json()
    assert body["status"] == "ok"
    assert body["checks"]["worker"]["ok"] is False  # поле остаётся, на статус не влияет


async def test_ready_broken_heartbeat_value_is_not_fresh(
    api: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_env(monkeypatch, TELEGRAM_MODE="polling")
    await svc.write_heartbeat(db)
    row = await db.get(SystemSetting, svc.HEARTBEAT_KEY)
    assert row is not None
    row.value = {"at": "не дата", "pid": 1}
    await db.commit()
    body = (await ready(api)).json()
    assert body["checks"]["worker"] == {"ok": False, "heartbeat_age_seconds": None}


async def test_ready_old_pending_outbox_is_degraded(
    api: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_env(monkeypatch, TELEGRAM_MODE="polling")
    await svc.write_heartbeat(db)
    db.add(
        NotificationOutbox(
            event_type="t",
            chat_id=1,
            payload={},
            text="x",
            status="pending",
            created_at=datetime.now(UTC) - timedelta(seconds=900),
        )
    )
    await db.commit()
    r = await ready(api)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["outbox"]["ok"] is False
    assert body["checks"]["outbox"]["pending"] == 1
    assert body["checks"]["outbox"]["oldest_pending_age_seconds"] >= 900


async def test_ready_old_pending_outbox_ignored_when_telegram_off(
    api: httpx.AsyncClient, db: AsyncSession
) -> None:
    db.add(
        NotificationOutbox(
            event_type="t",
            chat_id=1,
            payload={},
            text="x",
            status="pending",
            created_at=datetime.now(UTC) - timedelta(seconds=900),
        )
    )
    await db.commit()
    body = (await ready(api)).json()
    assert body["status"] == "ok"
    assert body["checks"]["outbox"]["ok"] is True
    assert body["checks"]["outbox"]["pending"] == 1


async def test_ready_down_503_on_migration_mismatch(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "head_revision", lambda: "9999")
    r = await ready(api)
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "down"
    assert body["checks"]["migrations"] == {"ok": False, "current": "0012", "head": "9999"}


async def test_ready_result_cached_for_two_seconds(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await ready(api)
    assert first.status_code == 200
    monkeypatch.setattr(svc, "head_revision", lambda: "9999")
    assert (await api.get(f"{API}/health/ready")).status_code == 200  # из кэша
    svc.reset_ready_cache()
    assert (await api.get(f"{API}/health/ready")).status_code == 503


async def test_ready_has_no_store_exemption_and_no_cache_header(api: httpx.AsyncClient) -> None:
    r = await ready(api)
    assert "no-store" not in r.headers.get("cache-control", "")


async def test_ready_down_when_db_unreachable(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(_: AsyncSession) -> bool:
        return False

    monkeypatch.setattr(svc, "check_db", broken)
    r = await ready(api)
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "down"
    assert body["checks"]["db"] == {"ok": False}
    assert body["checks"]["migrations"]["current"] is None


async def test_health_liveness_format_unchanged(api: httpx.AsyncClient) -> None:
    r = await api.get(f"{API}/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": True}


# ---------- heartbeat ----------


async def test_write_heartbeat_upserts_single_row(db: AsyncSession) -> None:
    first = await svc.write_heartbeat(db, datetime.now(UTC) - timedelta(seconds=60))
    await db.commit()
    second = await svc.write_heartbeat(db)
    await db.commit()
    rows = list(
        await db.scalars(select(SystemSetting).where(SystemSetting.key == svc.HEARTBEAT_KEY))
    )
    assert len(rows) == 1
    assert rows[0].value["pid"] == os.getpid()
    assert datetime.fromisoformat(rows[0].value["at"]) == second > first
    assert await svc.heartbeat_is_fresh(db) is True


async def test_heartbeat_is_fresh_false_without_row_or_when_old(db: AsyncSession) -> None:
    assert await svc.last_heartbeat(db) is None
    assert await svc.heartbeat_is_fresh(db) is False
    await svc.write_heartbeat(db, datetime.now(UTC) - timedelta(hours=1))
    assert await svc.heartbeat_is_fresh(db) is False


def test_worker_registers_heartbeat_task() -> None:
    assert "heartbeat" in worker.load_tasks()
    from app.core import periodic

    task = periodic.REGISTRY["heartbeat"]
    assert task.interval == float(get_settings().worker_heartbeat_seconds)


async def test_heartbeat_key_hidden_from_settings_api(
    api: httpx.AsyncClient, db: AsyncSession
) -> None:
    await svc.write_heartbeat(db)
    director = await make_user(db, Role.director)
    token = await login(api, director)
    r = await api.get(f"{API}/settings", headers=bearer(token))
    assert r.status_code == 200
    assert "_worker_heartbeat" not in r.text


# ---------- GET /system/status ----------


async def test_system_status_requires_director(api: httpx.AsyncClient, db: AsyncSession) -> None:
    assert (await api.get(f"{API}/system/status")).status_code == 401
    loc = await make_location(db)
    for role in (Role.manager, Role.mechanic):
        user = await make_user(db, role, locations=[loc])
        token = await login(api, user)
        r = await api.get(f"{API}/system/status", headers=bearer(token))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"


async def test_system_status_shape(
    api: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "last_success"
    marker.write_text("ok")
    use_env(
        monkeypatch,
        TELEGRAM_MODE="webhook",
        TELEGRAM_BOT_USERNAME="crm_test_bot",
        TELEGRAM_BOT_TOKEN="123456:SECRET-TOKEN-VALUE",
        TELEGRAM_WEBHOOK_SECRET="hook-secret-value",
        BACKUP_MARKER_PATH=str(marker),
        APP_VERSION="1.2.3",
    )
    await svc.write_heartbeat(db)
    now = datetime.now(UTC)
    db.add_all(
        [
            NotificationOutbox(
                event_type="t",
                chat_id=1,
                payload={},
                text="a",
                status="pending",
                created_at=now - timedelta(seconds=30),
            ),
            NotificationOutbox(event_type="t", chat_id=1, payload={}, text="b", status="failed"),
            NotificationOutbox(
                event_type="t",
                chat_id=1,
                payload={},
                text="c",
                status="failed",
                created_at=now - timedelta(hours=30),
            ),
        ]
    )
    director = await make_user(db, Role.director)
    token = await login(api, director)
    r = await api.get(f"{API}/system/status", headers=bearer(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "server_time", "app_timezone", "env", "migrations", "worker", "outbox",
        "telegram", "last_backup_at", "version",
    }  # fmt: skip
    assert body["app_timezone"] == "Europe/Moscow"
    assert body["env"] == "test"
    assert body["migrations"] == {"current": "0012", "head": "0012"}
    assert body["worker"]["ok"] is True and body["worker"]["last_heartbeat_at"]
    assert body["outbox"]["pending"] == 1
    assert body["outbox"]["failed_24h"] == 1
    assert 25 <= body["outbox"]["oldest_pending_age_seconds"] < 120
    assert body["telegram"] == {"mode": "webhook", "bot_username": "crm_test_bot"}
    assert body["last_backup_at"] is not None
    assert body["version"] == "1.2.3"
    # Секретов в ответе нет.
    for secret in ("SECRET-TOKEN-VALUE", "hook-secret-value", "postgresql", "crm_test_m12"):
        assert secret not in r.text


async def test_system_status_defaults(api: httpx.AsyncClient, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    token = await login(api, director)
    body = (await api.get(f"{API}/system/status", headers=bearer(token))).json()
    assert body["telegram"] == {"mode": "disabled", "bot_username": None}
    assert body["last_backup_at"] is None
    assert body["worker"] == {"last_heartbeat_at": None, "ok": False}
    assert body["outbox"] == {"pending": 0, "failed_24h": 0, "oldest_pending_age_seconds": None}
    assert body["version"] == "dev"


# ---------- заголовки безопасности ----------

SECURITY = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


async def test_security_headers_on_api_responses(api: httpx.AsyncClient) -> None:
    r = await api.get(f"{API}/users")  # 401 — ошибки тоже получают заголовки
    assert r.status_code == 401
    for name, value in SECURITY.items():
        assert r.headers[name] == value
    assert r.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers  # HSTS только в prod
    assert "server" not in r.headers and "x-powered-by" not in r.headers


async def test_health_not_no_store_but_has_nosniff(api: httpx.AsyncClient) -> None:
    r = await api.get(f"{API}/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers.get("cache-control") != "no-store"


async def test_security_headers_on_500_and_413(client: httpx.AsyncClient) -> None:
    r = await client.get("/_boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert r.json()["error"]["message"] == "Внутренняя ошибка сервера"
    assert "hunter2" not in r.text and "RuntimeError" not in r.text
    for name, value in SECURITY.items():
        assert r.headers[name] == value

    big = await client.post("/_echo", content=b"x" * (get_settings().max_body_bytes + 10))
    assert big.status_code == 413
    assert big.headers["x-content-type-options"] == "nosniff"
    assert big.json()["error"]["code"] == "payload_too_large"


async def test_hsts_only_in_prod_and_docs_hidden(prod_client: httpx.AsyncClient) -> None:
    r = await prod_client.get(f"{API}/health")
    assert r.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"
    assert (await prod_client.get("/api/docs")).status_code == 404
    assert (await prod_client.get("/api/redoc")).status_code == 404
    assert (await prod_client.get("/openapi.json")).status_code == 404


async def test_dev_docs_page_has_no_restrictive_csp(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers


# ---------- CORS ----------


async def cors_client(monkeypatch: pytest.MonkeyPatch, env: str, **vars_: str) -> httpx.AsyncClient:
    monkeypatch.setenv("ENV", env)  # build_app меняет os.environ; monkeypatch вернёт как было
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    for key, value in vars_.items():
        monkeypatch.setenv(key, value)
    app = build_app(env)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://t")


async def test_cors_dev_allows_only_configured_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await cors_client(
        monkeypatch,
        "test",
        PUBLIC_BASE_URL="http://localhost:5173/",
        CORS_ORIGINS="http://127.0.0.1:5173, *",
    ) as c:
        ok = await c.get(f"{API}/health", headers={"Origin": "http://localhost:5173"})
        assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert ok.headers["access-control-allow-credentials"] == "true"
        extra = await c.get(f"{API}/health", headers={"Origin": "http://127.0.0.1:5173"})
        assert extra.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        evil = await c.get(f"{API}/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in evil.headers
        pre = await c.options(
            f"{API}/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in pre.headers


async def test_cors_prod_sends_no_cors_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await cors_client(
        monkeypatch,
        "prod",
        PUBLIC_BASE_URL="https://crm.example.com",
        CORS_ORIGINS="https://other.example.com",
    ) as c:
        for origin in (
            "https://crm.example.com",
            "https://other.example.com",
            "https://evil.example",
        ):
            r = await c.get(f"{API}/health", headers={"Origin": origin})
            assert not [h for h in r.headers if h.startswith("access-control-")]
    get_settings.cache_clear()


# ---------- конфигурация ----------


def test_settings_defaults_and_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_TIMEZONE", "TELEGRAM_MODE", "PUBLIC_BASE_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.app_timezone == "Europe/Moscow"
    assert s.public_base_url == "http://localhost:5173"
    assert s.worker_heartbeat_seconds == 30
    assert s.ready_worker_max_age_seconds == 120
    assert s.ready_outbox_max_age_seconds == 300
    assert s.backup_retention_days == 30
    assert s.app_version == "dev"
    assert Settings(_env_file=None, telegram_mode="disabled").telegram_mode == "off"
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"


def test_settings_empty_secret_variables_mean_not_set() -> None:
    s = Settings(
        _env_file=None,
        telegram_bot_token="",
        telegram_webhook_secret="  ",
        seed_director_password="",
    )
    assert s.telegram_bot_token is None
    assert s.telegram_webhook_secret is None
    assert s.seed_director_password is None
    assert not s.telegram_enabled


def test_settings_rejects_bad_timezone() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_timezone="Mars/Olympus")


def test_cors_origin_list_empty_in_prod() -> None:
    s = Settings(_env_file=None, env="prod", cors_origins="https://x.example")
    assert s.cors_origin_list == []
    dev = Settings(_env_file=None, cors_origins="https://x.example, *, https://x.example")
    assert "*" not in dev.cors_origin_list
    assert dev.cors_origin_list.count("https://x.example") == 1


def test_prod_requires_database_url_and_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/x")
    monkeypatch.setenv("SECRET_KEY", "dev-only-change-me")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        get_settings()


# ---------- миграции и права ----------


def test_single_migration_head_is_0012() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(svc._MIGRATIONS_DIR))
    assert script.get_heads() == ["0012"]
    assert svc.head_revision() == "0012"


async def test_crm_app_cannot_modify_append_only_tables(db: AsyncSession) -> None:
    exists = await db.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = 'crm_app'"))
    if not exists:
        pytest.skip("роль crm_app не создана в тестовой БД")
    for table in ("audit_log", "stock_movements"):
        for priv in ("UPDATE", "DELETE", "TRUNCATE"):
            allowed = await db.scalar(
                text("SELECT has_table_privilege('crm_app', :t, :p)"), {"t": table, "p": priv}
            )
            assert allowed is False, (table, priv)
    for table in ("payments", "payroll_adjustments"):
        for priv in ("UPDATE", "DELETE"):
            allowed = await db.scalar(
                text("SELECT has_table_privilege('crm_app', :t, :p)"), {"t": table, "p": priv}
            )
            assert allowed is False, (table, priv)
