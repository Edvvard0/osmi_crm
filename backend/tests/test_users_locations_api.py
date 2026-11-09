import pytest
from sqlalchemy import select

from app.models import AuditLog, Location, Role
from tests.factories import PASSWORD, bearer, login, make_location, make_user

pytestmark = pytest.mark.integration

API = "/api/v1"
GOOD_PW = "another-long-passphrase-7"


@pytest.fixture
async def director(api, db):
    loc = await make_location(db, "Главная")
    user = await make_user(db, Role.director, locations=[loc])
    token = await login(api, user)
    return {"user": user, "loc": loc, "h": bearer(token)}


def body(**kw):
    base = {
        "login": "ivan.petrov",
        "full_name": "Иван Петров",
        "role": "mechanic",
        "password": GOOD_PW,
        "location_ids": [],
    }
    return {**base, **kw}


async def audit(db, entity_type, action=None):
    q = select(AuditLog).where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
    return list(await db.scalars(q.order_by(AuditLog.id)))


# ---------------- users: create ----------------


async def test_create_user_and_login_as_him(api, db, director):
    r = await api.post(
        f"{API}/users",
        headers=director["h"],
        json=body(login="Ivan.Petrov", location_ids=[str(director["loc"].id)]),
    )
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["login"] == "ivan.petrov" and u["role"] == "mechanic" and u["is_active"] is True
    assert u["location_ids"] == [str(director["loc"].id)]
    assert set(u) == {"id", "login", "full_name", "role", "is_active", "location_ids", "created_at"}
    assert GOOD_PW not in r.text and "hash" not in r.text

    rows = await audit(db, "user", "create")
    assert any(str(a.entity_id) == u["id"] and a.user_id == director["user"].id for a in rows)
    assert all("password" not in str(a.changes).lower() for a in rows)

    other = await api.post(f"{API}/auth/login", json={"login": "ivan.petrov", "password": GOOD_PW})
    assert other.status_code == 200 and other.json()["user"]["id"] == u["id"]


async def test_create_duplicate_login_is_409(api, director):
    assert (await api.post(f"{API}/users", headers=director["h"], json=body())).status_code == 201
    r = await api.post(f"{API}/users", headers=director["h"], json=body(full_name="Другой"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    r = await api.post(f"{API}/users", headers=director["h"], json=body(login="IVAN.PETROV"))
    assert r.status_code == 409


async def test_create_unknown_location(api, director):
    r = await api.post(
        f"{API}/users",
        headers=director["h"],
        json=body(location_ids=["00000000-0000-4000-8000-000000000009"]),
    )
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"location_ids": "unknown_location"}


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short", "password_too_short"),
        ("password123", "password_common"),
        ("ivan.petrov", "password_equals_login"),
    ],
)
async def test_create_weak_password(api, director, password, reason):
    r = await api.post(f"{API}/users", headers=director["h"], json=body(password=password))
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"password": reason}


@pytest.mark.parametrize(
    "extra",
    [
        {"is_active": False},
        {"id": "00000000-0000-4000-8000-000000000001"},
        {"password_hash": "x"},
        {"created_by": "00000000-0000-4000-8000-000000000001"},
        {"failed_login_count": 0},
        {"is_superuser": True},
    ],
)
async def test_create_mass_assignment_rejected(api, director, extra):
    r = await api.post(f"{API}/users", headers=director["h"], json=body(**extra))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "override",
    [
        {"role": "admin"},
        {"role": None},
        {"login": "ab"},
        {"login": "Иван"},
        {"full_name": ""},
        {"full_name": "   "},
        {"full_name": 5},
        {"location_ids": "x"},
        {"location_ids": ["not-a-uuid"]},
        {"password": ""},
    ],
)
async def test_create_validation(api, director, override):
    r = await api.post(f"{API}/users", headers=director["h"], json=body(**override))
    assert r.status_code == 422


# ---------------- users: read / update ----------------


async def test_get_user_and_404(api, db, director):
    u = await make_user(db, Role.manager)
    r = await api.get(f"{API}/users/{u.id}", headers=director["h"])
    assert r.status_code == 200 and r.json()["id"] == str(u.id)
    r = await api.get(f"{API}/users/00000000-0000-4000-8000-000000000001", headers=director["h"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert (await api.get(f"{API}/users/not-a-uuid", headers=director["h"])).status_code == 422


async def test_patch_user_fields_and_audit(api, db, director):
    loc2 = await make_location(db)
    u = await make_user(db, Role.mechanic, locations=[director["loc"]])
    r = await api.patch(
        f"{API}/users/{u.id}",
        headers=director["h"],
        json={"full_name": "Новое Имя", "role": "manager", "location_ids": [str(loc2.id)]},
    )
    assert r.status_code == 200
    assert r.json()["full_name"] == "Новое Имя" and r.json()["role"] == "manager"
    assert r.json()["location_ids"] == [str(loc2.id)]
    rows = [a for a in await audit(db, "user", "update") if a.entity_id == u.id]
    assert len(rows) == 1
    assert set(rows[0].changes) == {"full_name", "role", "location_ids"}


async def test_patch_noop_writes_no_audit(api, db, director):
    u = await make_user(db, Role.mechanic)
    r = await api.patch(f"{API}/users/{u.id}", headers=director["h"], json={})
    assert r.status_code == 200
    assert [a for a in await audit(db, "user", "update") if a.entity_id == u.id] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"login": "other.login"},
        {"password": "x"},
        {"password_hash": "x"},
        {"full_name": None},
        {"role": None},
        {"role": "root"},
        {"is_active": "maybe"},
    ],
)
async def test_patch_user_rejects_bad_fields(api, db, director, payload):
    u = await make_user(db)
    r = await api.patch(f"{API}/users/{u.id}", headers=director["h"], json=payload)
    assert r.status_code == 422


async def test_patch_unknown_user_404(api, director):
    r = await api.patch(
        f"{API}/users/00000000-0000-4000-8000-000000000001",
        headers=director["h"],
        json={"full_name": "X"},
    )
    assert r.status_code == 404


async def test_role_change_and_deactivation_revoke_sessions(api, db, conn, director):
    from tests.conftest import make_api_client

    u = await make_user(db, Role.manager)
    async with make_api_client(conn, ip="198.51.100.30") as c:
        await login(c, u)
        r = await api.patch(f"{API}/users/{u.id}", headers=director["h"], json={"role": "mechanic"})
        assert r.status_code == 200
        assert (await c.post(f"{API}/auth/refresh")).status_code == 401

        await login(c, u)
        r = await api.patch(f"{API}/users/{u.id}", headers=director["h"], json={"is_active": False})
        assert r.status_code == 200
        assert (await c.post(f"{API}/auth/refresh")).status_code == 401
        r = await c.post(f"{API}/auth/login", json={"login": u.login, "password": PASSWORD})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"

    # повторная активация снимает блокировку и возвращает вход
    r = await api.patch(f"{API}/users/{u.id}", headers=director["h"], json={"is_active": True})
    assert r.json()["is_active"] is True
    async with make_api_client(conn, ip="198.51.100.31") as c:
        assert (
            await c.post(f"{API}/auth/login", json={"login": u.login, "password": PASSWORD})
        ).status_code == 200


async def test_changing_name_does_not_revoke_sessions(api, db, conn, director):
    from tests.conftest import make_api_client

    u = await make_user(db, Role.manager)
    async with make_api_client(conn, ip="198.51.100.32") as c:
        await login(c, u)
        await api.patch(f"{API}/users/{u.id}", headers=director["h"], json={"full_name": "Имя"})
        assert (await c.post(f"{API}/auth/refresh")).status_code == 200


async def test_director_cannot_deactivate_or_demote_self(api, director):
    uid = director["user"].id
    for payload in ({"is_active": False}, {"role": "manager"}):
        r = await api.patch(f"{API}/users/{uid}", headers=director["h"], json=payload)
        assert r.status_code == 422
        assert r.json()["error"]["fields"] == {"_": "cannot_change_self"}
    # то же значение — не изменение
    r = await api.patch(f"{API}/users/{uid}", headers=director["h"], json={"role": "director"})
    assert r.status_code == 200


# ---------------- reset-password ----------------


async def test_reset_password_flow(api, db, conn, director):
    from tests.conftest import make_api_client

    u = await make_user(db, Role.manager)
    # блокируем аккаунт неудачными входами
    async with make_api_client(conn, ip="198.51.100.40") as c:
        await login(c, u)
        for _ in range(5):
            await c.post(
                f"{API}/auth/login", json={"login": u.login, "password": "wrong-pass-1234"}
            )
        r = await api.post(
            f"{API}/users/{u.id}/reset-password",
            headers=director["h"],
            json={"new_password": GOOD_PW},
        )
        assert r.status_code == 204
        assert (await c.post(f"{API}/auth/refresh")).status_code == 401  # сессии отозваны
        old = await c.post(f"{API}/auth/login", json={"login": u.login, "password": PASSWORD})
        assert old.status_code == 401
        new = await c.post(f"{API}/auth/login", json={"login": u.login, "password": GOOD_PW})
        assert new.status_code == 200  # блокировка снята
    rows = await audit(db, "user", "password_change")
    assert any(a.entity_id == u.id and a.user_id == director["user"].id for a in rows)
    assert all(GOOD_PW not in str(a.changes) for a in rows)


async def test_reset_password_errors(api, db, director):
    u = await make_user(db, login="some.user")
    for pw, reason in (("short", "password_too_short"), ("some.user", "password_too_short")):
        r = await api.post(
            f"{API}/users/{u.id}/reset-password", headers=director["h"], json={"new_password": pw}
        )
        assert r.status_code == 422 and r.json()["error"]["fields"] == {"new_password": reason}
    r = await api.post(
        f"{API}/users/{u.id}/reset-password",
        headers=director["h"],
        json={"new_password": "password123"},
    )
    assert r.json()["error"]["fields"] == {"new_password": "password_common"}
    r = await api.post(
        f"{API}/users/00000000-0000-4000-8000-000000000001/reset-password",
        headers=director["h"],
        json={"new_password": GOOD_PW},
    )
    assert r.status_code == 404
    r = await api.post(
        f"{API}/users/{u.id}/reset-password",
        headers=director["h"],
        json={"new_password": GOOD_PW, "x": 1},
    )
    assert r.status_code == 422


# ---------------- users: list ----------------


async def test_list_filters_search_pagination(api, db, director):
    loc2 = await make_location(db)
    a = await make_user(db, Role.mechanic, login="qq.alpha", locations=[loc2])
    b = await make_user(db, Role.manager, login="qq.beta", locations=[loc2])
    c = await make_user(db, Role.mechanic, login="qq.gamma", is_active=False)
    h = director["h"]

    async def ids(**params):
        r = await api.get(f"{API}/users", headers=h, params=params)
        assert r.status_code == 200, r.text
        return {x["id"] for x in r.json()["items"]}, r.json()["total"]

    got, total = await ids(search="qq.")
    assert got == {str(a.id), str(b.id), str(c.id)} and total == 3
    assert (await ids(search="qq.", role="mechanic"))[0] == {str(a.id), str(c.id)}
    assert (await ids(search="qq.", is_active="false"))[0] == {str(c.id)}
    assert (await ids(search="QQ.ALPHA"))[0] == {str(a.id)}  # регистронезависимо
    assert (await ids(location_id=str(loc2.id)))[0] == {str(a.id), str(b.id)}
    assert (await ids(search="Тестовый", limit=2))[0].__len__() == 2

    r = await api.get(f"{API}/users", headers=h, params={"search": "qq.", "limit": 2, "offset": 2})
    assert len(r.json()["items"]) == 1 and r.json()["total"] == 3
    r = await api.get(f"{API}/users", headers=h, params={"search": "qq.", "offset": 50})
    assert r.json() == {"items": [], "total": 3}


async def test_list_search_escapes_like_wildcards(api, db, director):
    p = await make_user(db, login="pct.user")
    q = await make_user(db, login="plain.user")
    u = await make_user(db, login="under.user")
    for user, name in ((p, "Скидка 100% Иван"), (q, "Скидка 100x Иван"), (u, "Имя_с_подчерком")):
        r = await api.patch(
            f"{API}/users/{user.id}", headers=director["h"], json={"full_name": name}
        )
        assert r.status_code == 200

    async def found(term):
        r = await api.get(f"{API}/users", headers=director["h"], params={"search": term})
        return {x["id"] for x in r.json()["items"]}

    assert await found("100%") == {str(p.id)}
    assert await found("100x") == {str(q.id)}
    assert await found("%") == {str(p.id)}
    assert await found("_с_") == {str(u.id)}
    assert await found("\\") == set()
    assert await found("%%%%") == set()
    assert await found("_" * 10) == set()


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"limit": "x"},
        {"offset": -1},
        {"role": "root"},
        {"location_id": "nope"},
        {"is_active": "perhaps"},
        {"search": "x" * 101},
    ],
)
async def test_list_param_validation(api, director, params):
    r = await api.get(f"{API}/users", headers=director["h"], params=params)
    assert r.status_code == 422


async def test_list_ignores_unknown_sort_params(api, director):
    r = await api.get(
        f"{API}/users", headers=director["h"], params={"sort": "password_hash;drop table users"}
    )
    assert r.status_code == 200


# ---------------- locations ----------------


async def test_location_create_read_update(api, db, director):
    h = director["h"]
    r = await api.post(
        f"{API}/locations",
        headers=h,
        json={"name": "Сервис Центр", "address": "ул. Ленина, 1", "phone": "8 (999) 123-45-67"},
    )
    assert r.status_code == 201, r.text
    loc = r.json()
    assert set(loc) == {
        "id", "name", "address", "phone", "is_active", "code", "timezone", "work_start", "work_end",
    }  # fmt: skip
    assert loc["phone"] == "+79991234567" and loc["is_active"] is True

    r = await api.get(f"{API}/locations/{loc['id']}", headers=h)
    assert r.json() == loc

    r = await api.patch(
        f"{API}/locations/{loc['id']}",
        headers=h,
        json={"name": "Новое имя", "is_active": False, "phone": None},
    )
    assert r.status_code == 200
    assert r.json() == {**loc, "name": "Новое имя", "is_active": False, "phone": None}
    rows = [a for a in await audit(db, "location") if str(a.entity_id) == loc["id"]]
    assert [a.action for a in rows] == ["create", "update"]
    assert set(rows[1].changes) == {"name", "is_active", "phone"}


async def test_location_codes_are_unique_and_duplicate_name_is_409(api, db, director):
    for i in range(3):
        r = await api.post(
            f"{API}/locations", headers=director["h"], json={"name": f"Центр {i}", "address": "а"}
        )
        assert r.status_code == 201
    codes = list(await db.scalars(select(Location.code).where(Location.name.like("Центр %"))))
    assert len(codes) == len(set(codes)) == 3
    r = await api.post(
        f"{API}/locations", headers=director["h"], json={"name": "Центр 0", "address": "б"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "A"},
        {"name": "", "address": "x"},
        {"name": "   ", "address": "x"},
        {"name": "A" * 101, "address": "x"},
        {"name": "A", "address": "x" * 256},
        {"name": "A", "address": "x", "phone": "123"},
        {"name": "A", "address": "x", "code": "HACK"},
        {"name": "A", "address": "x", "id": "00000000-0000-4000-8000-000000000001"},
        {"name": "A", "address": "x", "is_active": False},
        {"name": 5, "address": "x"},
    ],
)
async def test_location_create_validation(api, director, payload):
    r = await api.post(f"{API}/locations", headers=director["h"], json=payload)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "payload",
    [{"name": None}, {"address": None}, {"is_active": None}, {"code": "X"}, {"phone": "abc"}],
)
async def test_location_patch_validation(api, director, payload):
    r = await api.patch(
        f"{API}/locations/{director['loc'].id}", headers=director["h"], json=payload
    )
    assert r.status_code == 422


async def test_location_patch_unknown_404(api, director):
    r = await api.patch(
        f"{API}/locations/00000000-0000-4000-8000-000000000001",
        headers=director["h"],
        json={"name": "X"},
    )
    assert r.status_code == 404


async def test_location_patch_noop_no_audit(api, db, director):
    r = await api.patch(f"{API}/locations/{director['loc'].id}", headers=director["h"], json={})
    assert r.status_code == 200
    assert [a for a in await audit(db, "location", "update")] == []


async def test_no_delete_endpoints(api, db, director):
    u = await make_user(db)
    assert (
        await api.delete(f"{API}/locations/{director['loc'].id}", headers=director["h"])
    ).status_code == 405
    assert (await api.delete(f"{API}/users/{u.id}", headers=director["h"])).status_code == 405
