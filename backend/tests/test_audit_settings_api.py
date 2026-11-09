"""Модуль 11: журнал действий, сессии, системные настройки."""

# ruff: noqa: E501

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.api.v1.user_sessions import _mutations
from app.models import AuditLog, RefreshSession, Role, User
from app.models.system_settings import SystemSetting
from app.services import settings as settings_svc
from app.services.audit import write_audit
from app.services.audit_read import ENTITY_LABELS, audit_meta
from app.services.sessions import utcnow
from app.services.user_sessions import describe_device, session_cleanup
from tests.conftest import make_api_client
from tests.factories import PASSWORD, bearer, login, make_location, make_user

API = "/api/v1"
pytestmark = pytest.mark.integration

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"


@pytest.fixture(autouse=True)
def _clean_state() -> AsyncIterator[None]:
    settings_svc.invalidate_cache()
    _mutations.reset()
    yield  # type: ignore[misc]
    settings_svc.invalidate_cache()


async def sign_in(
    client: httpx.AsyncClient, user: User, ua: str = CHROME_WIN
) -> dict[str, str]:
    r = await client.post(
        f"{API}/auth/login",
        json={"login": user.login, "password": PASSWORD},
        headers={"User-Agent": ua},
    )
    assert r.status_code == 200, r.text
    return bearer(r.json()["access_token"])


def err_fields(r: httpx.Response) -> dict[str, str]:
    return r.json()["error"]["fields"]  # type: ignore[no-any-return]


# ---------- права ----------


async def test_only_director_reads_audit_and_settings(api: httpx.AsyncClient, db: AsyncSession) -> None:
    loc = await make_location(db)
    director = await make_user(db, Role.director)
    manager = await make_user(db, Role.manager, locations=[loc])
    mechanic = await make_user(db, Role.mechanic, locations=[loc])
    target = f"{API}/users/{uuid.uuid4()}/revoke-sessions"
    checks = [
        ("GET", f"{API}/audit-log", None),
        ("GET", f"{API}/audit-log/meta", None),
        ("GET", f"{API}/audit-log/1", None),
        ("GET", f"{API}/settings", None),
        ("PATCH", f"{API}/settings", {"session_retention_days": 30}),
        ("POST", target, None),
    ]
    for user in (manager, mechanic):
        h = bearer(await login(api, user))
        for method, url, body in checks:
            r = await api.request(method, url, json=body, headers=h)
            assert r.status_code == 403, (method, url, r.text)
    for method, url, body in checks:
        assert (await api.request(method, url, json=body)).status_code == 401
    h = bearer(await login(api, director))
    assert (await api.get(f"{API}/audit-log", headers=h)).status_code == 200
    assert (await api.get(f"{API}/audit-log/meta", headers=h)).status_code == 200


# ---------- журнал: чтение, фильтры, метки, секреты ----------


async def test_audit_list_filters_labels_and_paths(api: httpx.AsyncClient, db: AsyncSession) -> None:
    loc = await make_location(db, timezone="Asia/Vladivostok")
    director = await make_user(db, Role.director)
    other = await make_user(db, Role.manager, locations=[loc])
    order_id = uuid.uuid4()
    item_id = uuid.uuid4()
    write_audit(db, action="update", entity_type="user", user_id=director.id, entity_id=other.id,
                location_id=loc.id, changes={"role": {"old": "mechanic", "new": "manager"}})
    write_audit(db, action="create", entity_type="work_order_item", user_id=other.id,
                entity_id=item_id, location_id=loc.id, changes={"work_order_id": str(order_id)})
    write_audit(db, action="create", entity_type="payment", user_id=other.id, entity_id=uuid.uuid4())
    write_audit(db, action="login_failed", entity_type="user", changes={"login": "ghost", "reason": "unknown_login"})
    write_audit(db, action="update", entity_type="appointment", user_id=other.id, entity_id=uuid.uuid4(),
                location_id=loc.id, changes={"start_at": {"old": None, "new": "2026-11-10T20:30:00+00:00"}})
    db.add(AuditLog(action="update", entity_type="user", user_id=director.id, entity_id=other.id,
                    created_at=utcnow() - timedelta(days=40)))
    await db.commit()
    h = bearer(await login(api, director))

    r = await api.get(f"{API}/audit-log", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 6 - 1  # запись 40-дневной давности не входит в период по умолчанию
    ids = [e["id"] for e in body["items"]]
    assert ids == sorted(ids, reverse=True)

    r = await api.get(f"{API}/audit-log", params={"entity_type": "user", "action": "update", "user_id": str(director.id), "date_from": "2020-01-01", "date_to": "2030-01-01"}, headers=h)
    assert r.status_code == 422  # период > 366 суток
    assert "date_to" in err_fields(r)

    r = await api.get(f"{API}/audit-log", params={"entity_type": "user", "action": "update", "user_id": str(director.id)}, headers=h)
    items = r.json()["items"]
    assert r.json()["total"] == len(items) == 1
    e = items[0]
    assert e["entity_label"] == other.full_name
    assert e["entity_path"] == f"/users/{other.id}"
    assert e["user"] == {"id": str(director.id), "full_name": director.full_name}
    assert e["location"] == {"id": str(loc.id), "name": loc.name, "timezone": "Asia/Vladivostok"}
    assert e["changes"] == {"role": {"old": "mechanic", "new": "manager"}}

    # старая запись попадает при расширении периода
    r = await api.get(f"{API}/audit-log", params={"entity_type": "user", "action": "update", "user_id": str(director.id), "date_from": "2026-01-01"}, headers=h)
    assert r.json()["total"] == 2

    # системные записи и несколько значений через запятую
    r = await api.get(f"{API}/audit-log", params={"user_id": "system"}, headers=h)
    sys_items = r.json()["items"]
    assert [i["action"] for i in sys_items] == ["login_failed"]
    assert sys_items[0]["entity_id"] is None and sys_items[0]["entity_path"] is None
    r = await api.get(f"{API}/audit-log", params={"action": "create,login_failed", "entity_type": "work_order_item,payment,user"}, headers=h)
    assert {i["entity_type"] for i in r.json()["items"]} == {"work_order_item", "payment", "user"}
    assert r.json()["total"] == 3

    by_type = {i["entity_type"]: i for i in (await api.get(f"{API}/audit-log", params={"location_id": str(loc.id)}, headers=h)).json()["items"]}
    assert by_type["work_order_item"]["entity_path"] == f"/orders/{order_id}"
    # 20:30 UTC = 06:30 следующего дня во Владивостоке
    assert by_type["appointment"]["entity_path"] == "/calendar?date=2026-11-11"
    pay = (await api.get(f"{API}/audit-log", params={"entity_type": "payment"}, headers=h)).json()["items"][0]
    assert pay["entity_path"] is None  # в changes нет order_id

    # неизвестные значения и границы
    for params, key in (
        ({"action": "explode"}, "action"),
        ({"entity_type": "user,spaceship"}, "entity_type"),
        ({"offset": 10001}, "offset"),
        ({"date_from": "2026-11-05", "date_to": "2026-11-01"}, "date_to"),
        ({"user_id": "not-a-uuid"}, "user_id"),
        ({"limit": 201}, "limit"),
    ):
        r = await api.get(f"{API}/audit-log", params=params, headers=h)
        assert r.status_code == 422 and key in err_fields(r), (params, r.text)
    r = await api.get(f"{API}/audit-log", params={"user_id": str(uuid.uuid4()), "location_id": str(uuid.uuid4())}, headers=h)
    assert r.status_code == 200 and r.json() == {"items": [], "total": 0}

    # пагинация
    page = (await api.get(f"{API}/audit-log", params={"limit": 2, "offset": 1}, headers=h)).json()
    assert len(page["items"]) == 2 and page["total"] == body["total"]
    assert [i["id"] for i in page["items"]] == ids[1:3]


async def test_audit_detail_meta_and_redaction(api: httpx.AsyncClient, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    write_audit(db, action="update", entity_type="user", user_id=director.id, entity_id=director.id,
                changes={"password_hash": {"old": "a", "new": "b"}, "nested": {"api_token": "t", "ok": 1},
                         "list": [{"secret": "s"}], "sms_code": "1234", "barcode": "keep"})
    await db.commit()
    stored = (await db.scalars(select(AuditLog).where(AuditLog.entity_id == director.id, AuditLog.action == "update"))).one()
    assert stored.changes["password_hash"] == "***"  # маскируется уже при записи
    h = bearer(await login(api, director))

    r = await api.get(f"{API}/audit-log/{stored.id}", headers=h)
    assert r.status_code == 200
    ch = r.json()["changes"]
    assert ch["password_hash"] == "***" and ch["nested"] == {"api_token": "***", "ok": 1}
    assert ch["list"] == [{"secret": "***"}] and ch["sms_code"] == "***" and ch["barcode"] == "keep"
    assert (await api.get(f"{API}/audit-log/999999999999", headers=h)).status_code == 404

    # чтение маскирует и записи, сделанные в обход write_audit
    db.add(AuditLog(action="update", entity_type="user", entity_id=director.id, changes={"new_password": "x", "n": 1}))
    await db.commit()
    raw = (await db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))).one()
    assert (await api.get(f"{API}/audit-log/{raw.id}", headers=h)).json()["changes"] == {"new_password": "***", "n": 1}

    meta = (await api.get(f"{API}/audit-log/meta", headers=h)).json()
    assert meta == audit_meta().model_dump(mode="json")
    assert {a["value"] for a in meta["actions"]} >= {"export", "revoke_session", "login_failed"}
    assert {t["value"] for t in meta["entity_types"]} == set(ENTITY_LABELS)
    assert all(x["label"] for x in meta["actions"] + meta["entity_types"])


async def test_login_failed_hides_login_existence(api: httpx.AsyncClient, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    victim = await make_user(db, Role.manager)
    bad = await api.post(f"{API}/auth/login", json={"login": victim.login, "password": "wrong-password-1"})
    assert bad.status_code == 401
    h = bearer(await login(api, director))
    items = (await api.get(f"{API}/audit-log", params={"action": "login_failed"}, headers=h)).json()["items"]
    assert len(items) == 1
    assert items[0]["entity_id"] is None and items[0]["user"] is None
    assert items[0]["changes"] == {"login": victim.login, "reason": "bad_password"}


# ---------- системные настройки ----------


async def test_settings_get_patch_audit_and_cache(api: httpx.AsyncClient, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    h = bearer(await login(api, director))
    r = await api.get(f"{API}/settings", headers=h)
    assert r.status_code == 200
    assert r.json() == {
        "discount_alert_percent": "20.00",
        "daily_summary_time": "21:00",
        "session_retention_days": 30,
        "heatmap_thresholds": {"hours": [2, 5, 8], "actions": [5, 15, 30]},
        "updated_at": None,
        "updated_by": None,
    }
    assert await settings_svc.get_setting(db, "discount_alert_percent") == "20.00"

    r = await api.patch(f"{API}/settings", json={"discount_alert_percent": "35.5", "daily_summary_time": None, "heatmap_thresholds": {"hours": [1.5, 4, 9.5], "actions": [3, 10, 50]}}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discount_alert_percent"] == "35.50" and body["daily_summary_time"] is None
    assert body["heatmap_thresholds"] == {"hours": [1.5, 4, 9.5], "actions": [3, 10, 50]}
    assert body["updated_by"] == {"id": str(director.id), "full_name": director.full_name}
    assert body["updated_at"] is not None
    # PATCH сбросил кэш процесса: аксессор видит новое значение сразу
    assert await settings_svc.get_setting(db, "discount_alert_percent") == "35.50"
    assert await settings_svc.get_setting(db, "daily_summary_time") is None
    assert await settings_svc.get_setting(db, "session_retention_days") == 30

    entry = (await db.scalars(select(AuditLog).where(AuditLog.entity_type == "system_settings"))).one()
    assert (entry.action, entry.entity_id, entry.user_id) == ("update", None, director.id)
    assert entry.changes["discount_alert_percent"] == {"old": "20.00", "new": "35.50"}
    assert entry.changes["daily_summary_time"] == {"old": "21:00", "new": None}
    assert set(entry.changes) == {"discount_alert_percent", "daily_summary_time", "heatmap_thresholds"}

    # повтор без изменений — без нового аудита
    r = await api.patch(f"{API}/settings", json={"discount_alert_percent": "35.50"}, headers=h)
    assert r.status_code == 200
    n = len((await db.scalars(select(AuditLog).where(AuditLog.entity_type == "system_settings"))).all())
    assert n == 1
    shown = (await api.get(f"{API}/audit-log", params={"entity_type": "system_settings"}, headers=h)).json()["items"][0]
    assert shown["entity_path"] == "/system-settings" and shown["entity_id"] is None


async def test_settings_validation(api: httpx.AsyncClient, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    h = bearer(await login(api, director))
    bad: list[tuple[dict[str, object], str]] = [
        ({"discount_alert_percent": "0.99"}, "discount_alert_percent"),
        ({"discount_alert_percent": "100.01"}, "discount_alert_percent"),
        ({"discount_alert_percent": "10.123"}, "discount_alert_percent"),
        ({"discount_alert_percent": 10}, "discount_alert_percent"),
        ({"discount_alert_percent": None}, "discount_alert_percent"),
        ({"daily_summary_time": "24:00"}, "daily_summary_time"),
        ({"daily_summary_time": "9:00"}, "daily_summary_time"),
        ({"session_retention_days": 6}, "session_retention_days"),
        ({"session_retention_days": 366}, "session_retention_days"),
        ({"session_retention_days": True}, "session_retention_days"),
        ({"session_retention_days": "30"}, "session_retention_days"),
        ({"heatmap_thresholds": {"hours": [2, 2, 8], "actions": [5, 15, 30]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2, 5, 8], "actions": [30, 15, 5]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [0, 5, 8], "actions": [5, 15, 30]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2, 5, 24.5], "actions": [5, 15, 30]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2.25, 5, 8], "actions": [5, 15, 30]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2, 5, 8], "actions": [5, 15, 1001]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2, 5, 8], "actions": [5.5, 15, 30]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2, 5, 8]}}, "heatmap_thresholds"),
        ({"heatmap_thresholds": {"hours": [2, 5], "actions": [5, 15, 30]}}, "heatmap_thresholds"),
        ({"_worker_heartbeat": "x"}, "_worker_heartbeat"),
        ({"unknown_key": 1}, "unknown_key"),
    ]
    for body, key in bad:
        r = await api.patch(f"{API}/settings", json=body, headers=h)
        assert r.status_code == 422, (body, r.text)
        assert key in err_fields(r), (body, r.text)
    r = await api.patch(f"{API}/settings", json={}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    # ничего не записано
    assert (await db.scalars(select(SystemSetting))).all() == []
    assert (await api.get(f"{API}/settings", headers=h)).json()["updated_at"] is None


async def test_get_setting_ttl_cache_and_service_keys(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    director = await make_user(db, Role.director)
    clock = [1000.0]
    monkeypatch.setattr(settings_svc.time, "monotonic", lambda: clock[0])
    assert await settings_svc.get_setting(db, "session_retention_days") == 30
    db.add(SystemSetting(key="session_retention_days", value=90, updated_by=director.id))
    db.add(SystemSetting(key="_worker_heartbeat", value="2026-11-09T10:00:00+00:00"))
    await db.commit()
    assert await settings_svc.get_setting(db, "session_retention_days") == 30  # из кэша
    clock[0] += settings_svc.CACHE_TTL + 0.1
    assert await settings_svc.get_setting(db, "session_retention_days") == 90
    assert await settings_svc.get_setting(db, "_worker_heartbeat") == "2026-11-09T10:00:00+00:00"
    assert settings_svc.CACHE_TTL <= 10
    with pytest.raises(KeyError):
        await settings_svc.get_setting(db, "no_such_key")

    # служебные ключи не отдаются через /settings и не влияют на updated_at
    read = await settings_svc.read_settings(db)
    assert read.session_retention_days == 90 and read.updated_by is not None


# ---------- сессии ----------


def test_describe_device() -> None:
    assert describe_device(CHROME_WIN) == "Chrome · Windows"
    assert describe_device(SAFARI_IPHONE) == "Safari · iPhone"
    assert describe_device("Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0") == "Firefox · Linux"
    assert describe_device(None) == "Неизвестное устройство"
    assert describe_device("curl/8.0") == "Неизвестное устройство"


async def test_sessions_list_revoke_and_audit(conn: AsyncConnection, db: AsyncSession) -> None:
    user = await make_user(db, Role.manager)
    stranger = await make_user(db, Role.manager)
    director = await make_user(db, Role.director)
    async with make_api_client(conn, "203.0.113.10") as c1, make_api_client(conn, "198.51.100.7") as c2, make_api_client(conn, "192.0.2.1") as cs:
        h1 = await sign_in(c1, user, CHROME_WIN)
        h2 = await sign_in(c2, user, SAFARI_IPHONE)
        await sign_in(cs, stranger)
        # ротация токена второго устройства не создаёт новую сессию
        assert (await c2.post(f"{API}/auth/refresh", headers={"User-Agent": SAFARI_IPHONE})).status_code == 200
        r = await c1.get(f"{API}/auth/sessions", headers=h1)
        assert r.status_code == 200
        sessions = r.json()
        assert len(sessions) == 2
        assert sessions[0]["is_current"] is True and sessions[0]["device"] == "Chrome · Windows"
        assert sessions[0]["ip"] == "203.0.113.10" and sessions[0]["user_agent"] == CHROME_WIN
        other = sessions[1]
        assert other["is_current"] is False and other["device"] == "Safari · iPhone" and other["ip"] == "198.51.100.7"
        assert other["last_active_at"] >= other["created_at"]
        # без cookie current нет
        async with make_api_client(conn, "203.0.113.99") as bare:
            r = await bare.get(f"{API}/auth/sessions", headers=h1)
            assert [s["is_current"] for s in r.json()] == [False, False]

        # текущую завершить нельзя, чужую/несуществующую — 404
        r = await c1.delete(f"{API}/auth/sessions/{sessions[0]['id']}", headers=h1)
        assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
        stranger_sid = (await cs.get(f"{API}/auth/sessions", headers=await sign_in(cs, stranger))).json()[0]["id"]
        assert (await c1.delete(f"{API}/auth/sessions/{stranger_sid}", headers=h1)).status_code == 404
        assert (await c1.delete(f"{API}/auth/sessions/{uuid.uuid4()}", headers=h1)).status_code == 404

        # завершение чужого устройства: refresh перестаёт работать, аудит, идемпотентность
        assert (await c1.delete(f"{API}/auth/sessions/{other['id']}", headers=h1)).status_code == 204
        assert (await c2.post(f"{API}/auth/refresh")).status_code == 401
        assert (await c1.delete(f"{API}/auth/sessions/{other['id']}", headers=h1)).status_code == 204
        assert len((await c1.get(f"{API}/auth/sessions", headers=h1)).json()) == 1
        entries = (await db.scalars(select(AuditLog).where(AuditLog.action == "revoke_session"))).all()
        assert len(entries) == 1
        assert (entries[0].entity_type, str(entries[0].entity_id), entries[0].user_id) == ("session", other["id"], user.id)
        del h2

        # revoke-others: без cookie 401 invalid_token
        async with make_api_client(conn, "203.0.113.98") as bare:
            r = await bare.post(f"{API}/auth/sessions/revoke-others", headers=h1)
            assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
        async with make_api_client(conn, "198.51.100.8") as c3:
            await sign_in(c3, user)
            await sign_in(c3, user)  # ещё одна сессия на том же клиенте
            assert (await c1.post(f"{API}/auth/sessions/revoke-others", headers=h1)).status_code == 204
            assert (await c3.post(f"{API}/auth/refresh")).status_code == 401
        assert (await c1.post(f"{API}/auth/refresh")).status_code == 200  # текущая жива
        last = (await db.scalars(select(AuditLog).where(AuditLog.action == "revoke_session").order_by(AuditLog.id.desc()).limit(1))).one()
        assert last.changes == {"count": 2} and last.entity_type == "session"

        # руководитель завершает все сессии сотрудника
        dh = await sign_in(c2, director)
        r = await c2.post(f"{API}/users/{user.id}/revoke-sessions", headers=dh)
        assert r.status_code == 204
        assert (await c1.post(f"{API}/auth/refresh")).status_code == 401
        ev = (await db.scalars(select(AuditLog).where(AuditLog.entity_type == "user", AuditLog.action == "revoke_session"))).one()
        assert (ev.entity_id, ev.user_id, ev.changes) == (user.id, director.id, {"count": 1})
        assert (await c2.post(f"{API}/users/{uuid.uuid4()}/revoke-sessions", headers=dh)).status_code == 404


async def test_director_revoke_own_sessions_keeps_current(conn: AsyncConnection, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    async with make_api_client(conn, "203.0.113.20") as a, make_api_client(conn, "203.0.113.21") as b:
        await sign_in(a, director)
        await db.execute(text("UPDATE refresh_sessions SET created_at = created_at - interval '1 hour'"))
        hb = await sign_in(b, director)  # самая свежая
        r = await b.post(f"{API}/users/{director.id}/revoke-sessions", headers=hb)
        assert r.status_code == 204
        assert (await b.post(f"{API}/auth/refresh")).status_code == 200
        assert (await a.post(f"{API}/auth/refresh")).status_code == 401


async def test_sessions_mutation_rate_limit(conn: AsyncConnection, db: AsyncSession) -> None:
    user = await make_user(db, Role.mechanic)
    async with make_api_client(conn) as c:
        h = await sign_in(c, user)
        codes = [(await c.delete(f"{API}/auth/sessions/{uuid.uuid4()}", headers=h)).status_code for _ in range(31)]
        assert codes[:30] == [404] * 30 and codes[30] == 429
        assert (await c.get(f"{API}/auth/sessions", headers=h)).status_code == 200  # чтение не лимитируется


async def test_last_login_at_and_session_cleanup(api: httpx.AsyncClient, db: AsyncSession) -> None:
    director = await make_user(db, Role.director)
    r = await api.post(f"{API}/auth/login", json={"login": director.login, "password": PASSWORD})
    assert r.json()["user"]["last_login_at"] is not None
    h = bearer(r.json()["access_token"])
    assert (await api.get(f"{API}/auth/me", headers=h)).json()["last_login_at"] is not None
    assert (await api.get(f"{API}/users/{director.id}", headers=h)).json()["last_login_at"] is not None
    fresh = await make_user(db, Role.manager)
    assert (await api.get(f"{API}/users/{fresh.id}", headers=h)).json()["last_login_at"] is None

    now = utcnow()

    def row(**kw: object) -> RefreshSession:
        return RefreshSession(user_id=director.id, token_hash=uuid.uuid4().hex + uuid.uuid4().hex, family_id=uuid.uuid4(), expires_at=now + timedelta(days=5), **kw)  # type: ignore[arg-type]

    old_revoked = row(revoked_at=now - timedelta(days=31))
    old_expired = row()
    old_expired.expires_at = now - timedelta(days=45)
    recent_revoked = row(revoked_at=now - timedelta(days=29))
    live = row()
    db.add_all([old_revoked, old_expired, recent_revoked, live])
    await db.commit()
    keep_ids = {recent_revoked.id, live.id}
    gone_ids = {old_revoked.id, old_expired.id}
    assert await session_cleanup(db) == 2
    left = set((await db.scalars(select(RefreshSession.id))).all())
    assert keep_ids <= left and not (gone_ids & left)

    # срок хранения берётся из настройки
    await db.execute(text("INSERT INTO system_settings (key, value) VALUES ('session_retention_days', '7')"))
    settings_svc.invalidate_cache()
    recent_revoked.revoked_at = now - timedelta(days=8)
    await db.commit()
    assert await session_cleanup(db) == 1
