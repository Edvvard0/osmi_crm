"""Инъекции из tests/security/payloads.py во все текстовые поля модуля 1."""

import uuid

import pytest
from sqlalchemy import func, select, text

from app.core.ratelimit import login_limiter
from app.models import Location, Role, User
from tests.factories import PASSWORD, bearer, login, make_location, make_user
from tests.security.payloads import ALL

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture
async def director(api, db):
    loc = await make_location(db, "Главная")
    user = await make_user(db, Role.director, locations=[loc])
    return bearer(await login(api, user))


def _assert_neutral(value: str) -> None:
    assert "\x00" not in value and "<" not in value and ">" not in value


def _login_name() -> str:
    return f"inj.{uuid.uuid4().hex[:10]}"


async def _tables_intact(db) -> None:
    # SQLi-payload не должен ни ломать схему, ни добавлять лишних записей
    await db.execute(text("SELECT 1 FROM users LIMIT 1"))
    await db.execute(text("SELECT 1 FROM locations LIMIT 1"))


@pytest.mark.parametrize("payload", ALL)
async def test_login_field(api, db, payload):
    await make_user(db, login="victim.user")
    login_limiter.reset()
    r = await api.post(f"{API}/auth/login", json={"login": payload, "password": PASSWORD})
    assert r.status_code in (401, 422), r.text
    assert "access_token" not in r.text
    assert payload not in r.text or len(payload) < 3
    await _tables_intact(db)


@pytest.mark.parametrize("payload", ALL)
async def test_password_field_never_authenticates(api, db, payload):
    user = await make_user(db, login="victim.user")
    login_limiter.reset()
    r = await api.post(f"{API}/auth/login", json={"login": user.login, "password": payload})
    assert r.status_code in (401, 422)
    assert "access_token" not in r.text


@pytest.mark.parametrize("payload", ALL)
async def test_user_full_name(api, db, director, payload):
    r = await api.post(
        f"{API}/users",
        headers=director,
        json={
            "login": _login_name(),
            "full_name": payload,
            "role": "mechanic",
            "password": "another-long-passphrase-7",
            "location_ids": [],
        },
    )
    assert r.status_code in (201, 422), r.text
    if r.status_code == 201:
        stored = r.json()["full_name"]
        _assert_neutral(stored)
        got = await db.scalar(select(User.full_name).where(User.id == uuid.UUID(r.json()["id"])))
        assert got == stored
        # SQL-текст хранится как данные, а не исполняется
        if "DROP TABLE" in payload:
            assert "DROP TABLE" in stored
    await _tables_intact(db)


@pytest.mark.parametrize("payload", ALL)
async def test_user_login_on_create(api, db, director, payload):
    r = await api.post(
        f"{API}/users",
        headers=director,
        json={
            "login": payload,
            "full_name": "Имя",
            "role": "mechanic",
            "password": "another-long-passphrase-7",
            "location_ids": [],
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("payload", ALL)
async def test_location_name_and_address(api, db, director, payload):
    r = await api.post(
        f"{API}/locations",
        headers=director,
        json={"name": payload, "address": payload, "phone": None},
    )
    assert r.status_code in (201, 422), r.text
    if r.status_code == 201:
        body = r.json()
        _assert_neutral(body["name"])
        _assert_neutral(body["address"])
        r2 = await api.patch(
            f"{API}/locations/{body['id']}", headers=director, json={"address": payload}
        )
        assert r2.status_code == 200
        _assert_neutral(r2.json()["address"])
    await _tables_intact(db)


@pytest.mark.parametrize("payload", [p for p in ALL if len(p) < 1000])
async def test_search_and_filters(api, db, director, payload):
    r = await api.get(f"{API}/users", headers=director, params={"search": payload})
    assert r.status_code in (200, 422), r.text
    for key in ("role", "location_id", "is_active", "limit", "offset"):
        r = await api.get(f"{API}/users", headers=director, params={key: payload})
        assert r.status_code == 422, key
    await _tables_intact(db)


@pytest.mark.parametrize("payload", ["' OR 1=1--", "1; DROP TABLE users", "../etc/passwd", "%00"])
async def test_path_ids(api, director, payload):
    for path in (f"/users/{payload}", f"/locations/{payload}"):
        r = await api.get(f"{API}{path}", headers=director)
        assert r.status_code in (404, 422)


async def test_sql_payload_is_stored_verbatim_and_users_survive(api, db, director):
    payload = "'; DROP TABLE users;--"
    before = await db.scalar(select(func.count()).select_from(User))
    r = await api.post(
        f"{API}/users",
        headers=director,
        json={
            "login": _login_name(),
            "full_name": payload,
            "role": "mechanic",
            "password": "another-long-passphrase-7",
            "location_ids": [],
        },
    )
    assert r.status_code == 201 and r.json()["full_name"] == payload
    assert await db.scalar(select(func.count()).select_from(User)) == before + 1
    assert await db.scalar(select(func.count()).select_from(Location)) >= 1


@pytest.mark.parametrize("bad", ["not json", "[]", "null", '"str"'])
async def test_malformed_bodies(api, bad):
    r = await api.post(
        f"{API}/auth/login", content=bad, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422


@pytest.mark.parametrize("token", ["", "Bearer", "Bearer ", "Bearer a.b.c", "Bearer " + "A" * 5000])
async def test_authorization_header_garbage(api, token):
    r = await api.get(f"{API}/auth/me", headers={"Authorization": token})
    assert r.status_code == 401
