"""Матрица прав: эндпоинт x роль, плюс изоляция по точкам."""

import uuid

import pytest

from app.models import Role
from tests.factories import bearer, login, make_location, make_user

pytestmark = pytest.mark.integration

API = "/api/v1"
ANY_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
async def world(api, db):
    loc_a = await make_location(db, "Точка А")
    loc_b = await make_location(db, "Точка Б")
    users = {
        "director": await make_user(db, Role.director, locations=[loc_a, loc_b]),
        "manager": await make_user(db, Role.manager, locations=[loc_a]),
        "mechanic": await make_user(db, Role.mechanic, locations=[loc_a]),
    }
    tokens = {name: await login(api, u) for name, u in users.items()}
    return {"loc_a": loc_a, "loc_b": loc_b, "users": users, "tokens": tokens}


def _new_user_body() -> dict:
    return {
        "login": f"new.{uuid.uuid4().hex[:8]}",
        "full_name": "Новый Сотрудник",
        "role": "mechanic",
        "password": "another-long-passphrase-7",
        "location_ids": [],
    }


# (метод, путь-шаблон, тело, кто может)
DIRECTOR_ONLY = [
    ("GET", "/users", None),
    ("POST", "/users", "new_user"),
    ("GET", "/users/{uid}", None),
    ("PATCH", "/users/{uid}", {"full_name": "Другое Имя"}),
    ("POST", "/users/{uid}/reset-password", {"new_password": "yet-another-passphrase-3"}),
    ("POST", "/locations", {"name": "Новая точка", "address": "ул. Новая, 5"}),
    ("PATCH", "/locations/{lid}", {"name": "Переименована"}),
]
ANY_AUTHENTICATED = [
    ("GET", "/auth/me", None),
    ("GET", "/locations", None),
    ("GET", "/locations/{lid}", None),
]


def _request(world, method, path, body):
    target = world["users"]["mechanic"]
    path = path.format(uid=target.id, lid=world["loc_a"].id)
    if body == "new_user":
        body = _new_user_body()
    return method, f"{API}{path}", body


@pytest.mark.parametrize(("method", "path", "body"), DIRECTOR_ONLY + ANY_AUTHENTICATED)
async def test_anonymous_gets_401(api, world, method, path, body):
    m, url, b = _request(world, method, path, body)
    r = await api.request(m, url, json=b)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("role", ["mechanic", "manager"])
@pytest.mark.parametrize(("method", "path", "body"), DIRECTOR_ONLY)
async def test_non_director_gets_403(api, world, role, method, path, body):
    m, url, b = _request(world, method, path, body)
    r = await api.request(m, url, json=b, headers=bearer(world["tokens"][role]))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(("method", "path", "body"), DIRECTOR_ONLY)
async def test_director_is_allowed(api, world, method, path, body):
    m, url, b = _request(world, method, path, body)
    r = await api.request(m, url, json=b, headers=bearer(world["tokens"]["director"]))
    assert r.status_code in (200, 201, 204), r.text


@pytest.mark.parametrize("role", ["mechanic", "manager", "director"])
@pytest.mark.parametrize(("method", "path", "body"), ANY_AUTHENTICATED)
async def test_any_role_can_read_own(api, world, role, method, path, body):
    m, url, b = _request(world, method, path, body)
    r = await api.request(m, url, json=b, headers=bearer(world["tokens"][role]))
    assert r.status_code == 200


@pytest.mark.parametrize("role", ["mechanic", "manager"])
async def test_foreign_location_is_404_and_indistinguishable(api, world, role):
    h = bearer(world["tokens"][role])
    foreign = await api.get(f"{API}/locations/{world['loc_b'].id}", headers=h)
    missing = await api.get(f"{API}/locations/{ANY_ID}", headers=h)
    assert foreign.status_code == missing.status_code == 404
    f, m = foreign.json()["error"], missing.json()["error"]
    assert (f["code"], f["message"]) == (m["code"], m["message"])
    assert world["loc_b"].name not in foreign.text


@pytest.mark.parametrize("role", ["mechanic", "manager"])
async def test_list_locations_only_own(api, world, role):
    r = await api.get(f"{API}/locations", headers=bearer(world["tokens"][role]))
    assert [x["id"] for x in r.json()] == [str(world["loc_a"].id)]


async def test_director_sees_all_locations(api, world):
    r = await api.get(f"{API}/locations", headers=bearer(world["tokens"]["director"]))
    assert {x["id"] for x in r.json()} == {str(world["loc_a"].id), str(world["loc_b"].id)}
    r = await api.get(
        f"{API}/locations/{world['loc_b'].id}", headers=bearer(world["tokens"]["director"])
    )
    assert r.status_code == 200


async def test_access_follows_binding_changes_immediately(api, world):
    """Привязка читается из БД на каждый запрос: отвязка сразу закрывает доступ."""
    d = bearer(world["tokens"]["director"])
    m = bearer(world["tokens"]["manager"])
    uid = world["users"]["manager"].id
    assert (await api.get(f"{API}/locations/{world['loc_a'].id}", headers=m)).status_code == 200
    r = await api.patch(f"{API}/users/{uid}", headers=d, json={"location_ids": []})
    assert r.status_code == 200
    assert (await api.get(f"{API}/locations/{world['loc_a'].id}", headers=m)).status_code == 404
    assert (await api.get(f"{API}/locations", headers=m)).json() == []


async def test_deactivated_user_token_stops_working(api, world):
    d = bearer(world["tokens"]["director"])
    uid = world["users"]["manager"].id
    await api.patch(f"{API}/users/{uid}", headers=d, json={"is_active": False})
    r = await api.get(f"{API}/auth/me", headers=bearer(world["tokens"]["manager"]))
    assert r.status_code == 401


async def test_role_change_applies_to_existing_token(api, world):
    d = bearer(world["tokens"]["director"])
    m = bearer(world["tokens"]["manager"])
    uid = world["users"]["manager"].id
    assert (await api.get(f"{API}/users", headers=m)).status_code == 403
    await api.patch(f"{API}/users/{uid}", headers=d, json={"role": "director"})
    assert (await api.get(f"{API}/users", headers=m)).status_code == 200
