"""Модуль 2: клиенты, автомобили, поиск — API, права, дубли, поиск, инъекции."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.schemas.client import ClientCreate, ClientUpdate, VehicleCreate
from tests.factories import bearer, login, make_location, make_user
from tests.security.payloads import ALL

API = "/api/v1"
VIN1 = "XTA210990Y2766389"
VIN2 = "WVWZZZ1JZXW000001"


# ---------------- unit: схемы (без БД) ----------------


@pytest.mark.parametrize(
    "raw",
    ["+7 (999) 123-45-67", "8 999 123 45 67", "89991234567", "79991234567", "+79991234567"],
)
def test_phone_normalized_to_e164(raw):
    c = ClientCreate(client_type="person", full_name="Иван", phone=raw)
    assert c.phone == "+79991234567"


@pytest.mark.parametrize("raw", ["123", "+1 202 555 0100", "abc", "8999123456", "+7999123456789"])
def test_phone_invalid(raw):
    with pytest.raises(ValueError):
        ClientCreate(client_type="person", full_name="Иван", phone=raw)


def test_plate_normalized():
    v = VehicleCreate(make="Kia", model="Rio", plate_number="a 123 bc 77")
    assert v.plate_number == "А123ВС77"  # латиница → кириллица, верхний регистр


@pytest.mark.parametrize(
    "vin",
    [
        "XTA210990Y276638",
        "XTA210990Y27663890",
        "XTA210990Y2766I89",
        "XTA210990Y2766O89",
        "XTA210990Y2766Q89",
        "XTA210990Y27663-9",
    ],
)
def test_vin_invalid(vin):
    with pytest.raises(ValueError):
        VehicleCreate(make="Kia", model="Rio", vin=vin)


def test_vin_uppercased_and_blank_is_none():
    assert VehicleCreate(make="Kia", model="Rio", vin=VIN1.lower()).vin == VIN1
    assert VehicleCreate(make="Kia", model="Rio", vin="  ").vin is None


def test_email_and_inn():
    assert (
        ClientCreate(
            client_type="person",
            full_name="И",
            phone="89991234567",
            email="Ivan@Mail.RU",
            inn="7707083893",
        ).email
        == "ivan@mail.ru"
    )
    for bad in ("not-an-email", "a@b", "a b@c.ru", "a\x00@b.ru", "<a>@b.ru"):
        with pytest.raises(ValueError):
            ClientCreate(client_type="person", full_name="И", phone="89991234567", email=bad)
    with pytest.raises(ValueError):
        ClientCreate(client_type="person", full_name="И", phone="89991234567", inn="123")


def test_update_null_rules():
    assert ClientUpdate(notes=None).model_dump(exclude_unset=True) == {"notes": None}
    with pytest.raises(ValueError):
        ClientUpdate(full_name=None)


# ---------------- integration ----------------

integration = pytest.mark.integration


@pytest.fixture
async def ctx(api, db):
    loc = await make_location(db, "Главная")
    manager = await make_user(db, Role.manager, locations=[loc])
    director = await make_user(db, Role.director)
    mechanic = await make_user(db, Role.mechanic, locations=[loc])
    return {
        "m": bearer(await login(api, manager)),
        "d": bearer(await login(api, director)),
        "x": bearer(await login(api, mechanic)),
        "manager": manager,
    }


def cbody(**kw):
    base = {"client_type": "person", "full_name": "Иванов Иван", "phone": "+7 999 123-45-67"}
    return {**base, **kw}


def vbody(**kw):
    base = {"make": "Toyota", "model": "Camry"}
    return {**base, **kw}


async def mk_client(api, h, **kw):
    r = await api.post(f"{API}/clients", headers=h, json=cbody(**kw))
    assert r.status_code == 201, r.text
    return r.json()


async def mk_vehicle(api, h, client_id, **kw):
    r = await api.post(f"{API}/clients/{client_id}/vehicles", headers=h, json=vbody(**kw))
    assert r.status_code == 201, r.text
    return r.json()


async def audit(db, entity_type, action=None):
    q = select(AuditLog).where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
    return list(await db.scalars(q.order_by(AuditLog.id)))


@integration
async def test_create_client_contract_shape(api, db, ctx):
    r = await api.post(
        f"{API}/clients",
        headers=ctx["m"],
        json=cbody(
            client_type="company",
            company_name="ООО Ромашка",
            inn="7707083893",
            phone_extra="8 912 000 11 22",
            email="Info@Romashka.ru",
            source="referral",
            discount_percent=7.5,
            notes="VIP",
        ),
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert set(c) == {
        "id", "client_type", "full_name", "company_name", "inn", "phone", "phone_extra", "email",
        "source", "discount_percent", "notes", "vehicles_count", "created_at", "archived_at",
    }  # fmt: skip
    assert c["phone"] == "+79991234567" and c["phone_extra"] == "+79120001122"
    assert c["discount_percent"] == 7.5 and c["email"] == "info@romashka.ru"
    assert c["vehicles_count"] == 0 and c["archived_at"] is None
    rows = await audit(db, "client", "create")
    assert any(str(a.entity_id) == c["id"] and a.user_id == ctx["manager"].id for a in rows)

    d = (await api.get(f"{API}/clients/{c['id']}", headers=ctx["d"])).json()
    assert d["vehicles"] == [] and d["id"] == c["id"]


@integration
async def test_defaults_and_blank_optional_fields(api, ctx):
    c = await mk_client(api, ctx["m"], inn="", email="", notes="  ", source="")
    assert c["discount_percent"] == 0 and c["inn"] is None and c["email"] is None
    assert c["source"] is None and c["notes"] is None


@integration
@pytest.mark.parametrize(
    "extra",
    [
        {"discount_percent": 101},
        {"discount_percent": -1},
        {"discount_percent": 10.123},
        {"client_type": "alien"},
        {"source": "tv"},
        {"inn": "123"},
        {"phone": "12345"},
        {"full_name": "   "},
        {"archived_at": "2020-01-01T00:00:00Z"},
        {"id": str(uuid.uuid4())},
        {"created_by": str(uuid.uuid4())},
        {"vehicles_count": 5},
    ],
)
async def test_create_client_validation_and_mass_assignment(api, ctx, extra):
    r = await api.post(f"{API}/clients", headers=ctx["m"], json=cbody(**extra))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


@integration
async def test_duplicate_phone_details_and_archived_not_blocking(api, db, ctx):
    first = await mk_client(api, ctx["m"])
    r = await api.post(
        f"{API}/clients", headers=ctx["m"], json=cbody(full_name="Другой", phone="89991234567")
    )
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "duplicate_phone"
    assert err["details"] == {"existing_id": first["id"], "existing_name": "Иванов Иван"}
    assert "uq_" not in r.text and "INSERT" not in r.text

    # архивный клиент телефон не блокирует
    assert (
        await api.post(f"{API}/clients/{first['id']}/archive", headers=ctx["m"])
    ).status_code == 200
    second = await mk_client(api, ctx["m"], full_name="Новый владелец")
    # восстановление архивного дубля запрещено
    r = await api.post(f"{API}/clients/{first['id']}/restore", headers=ctx["m"])
    assert r.status_code == 409 and r.json()["error"]["details"]["existing_id"] == second["id"]


@integration
async def test_update_phone_to_existing_is_409_and_self_is_fine(api, ctx):
    a = await mk_client(api, ctx["m"])
    b = await mk_client(api, ctx["m"], full_name="Петров", phone="+79990000001")
    r = await api.patch(f"{API}/clients/{b['id']}", headers=ctx["m"], json={"phone": "89991234567"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_phone"
    r = await api.patch(
        f"{API}/clients/{a['id']}", headers=ctx["m"], json={"phone": "8 999 123 45 67"}
    )
    assert r.status_code == 200


@integration
async def test_update_client_audit_and_null(api, db, ctx):
    c = await mk_client(api, ctx["m"], notes="старое", discount_percent=5)
    r = await api.patch(
        f"{API}/clients/{c['id']}",
        headers=ctx["d"],
        json={"notes": None, "discount_percent": 12.5, "full_name": "Иванов И.И."},
    )
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["notes"] is None and u["discount_percent"] == 12.5 and u["full_name"] == "Иванов И.И."
    rows = await audit(db, "client", "update")
    assert rows and rows[-1].changes["notes"] == {"old": "старое", "new": None}
    # без изменений — без записи в журнал
    n = len(rows)
    await api.patch(f"{API}/clients/{c['id']}", headers=ctx["d"], json={"notes": None})
    assert len(await audit(db, "client", "update")) == n
    r = await api.patch(f"{API}/clients/{c['id']}", headers=ctx["d"], json={"full_name": None})
    assert r.status_code == 422
    r = await api.patch(f"{API}/clients/{c['id']}", headers=ctx["d"], json={"archived_at": None})
    assert r.status_code == 422


@integration
async def test_client_with_two_vehicles_scenario(api, db, ctx):
    c = await mk_client(api, ctx["m"])
    v1 = await mk_vehicle(
        api, ctx["m"], c["id"], vin=VIN1.lower(), plate_number="a123bc77", year=2018, mileage=55000
    )
    v2 = await mk_vehicle(api, ctx["m"], c["id"], make="Kia", model="Rio", color="белый")
    assert v1["vin"] == VIN1 and v1["plate_number"] == "А123ВС77" and v1["client_id"] == c["id"]
    assert set(v1) == {
        "id", "client_id", "make", "model", "year", "vin", "plate_number", "color", "mileage",
        "notes", "created_at", "archived_at",
    }  # fmt: skip

    detail = (await api.get(f"{API}/clients/{c['id']}", headers=ctx["m"])).json()
    assert detail["vehicles_count"] == 2
    assert [v["id"] for v in detail["vehicles"]] == [v1["id"], v2["id"]]
    listed = (await api.get(f"{API}/clients/{c['id']}/vehicles", headers=ctx["m"])).json()
    assert [v["id"] for v in listed] == [v1["id"], v2["id"]]

    one = (await api.get(f"{API}/vehicles/{v1['id']}", headers=ctx["m"])).json()
    assert one["client"] == {"id": c["id"], "full_name": "Иванов Иван", "phone": "+79991234567"}

    r = await api.patch(
        f"{API}/vehicles/{v2['id']}", headers=ctx["m"], json={"mileage": 1000, "color": None}
    )
    assert r.status_code == 200 and r.json()["mileage"] == 1000 and r.json()["color"] is None

    assert (
        await api.post(f"{API}/vehicles/{v2['id']}/archive", headers=ctx["m"])
    ).status_code == 200
    detail = (await api.get(f"{API}/clients/{c['id']}", headers=ctx["m"])).json()
    assert detail["vehicles_count"] == 1 and [v["id"] for v in detail["vehicles"]] == [v1["id"]]
    all_v = (
        await api.get(
            f"{API}/clients/{c['id']}/vehicles", headers=ctx["m"], params={"include_archived": True}
        )
    ).json()
    assert len(all_v) == 2
    assert (await api.post(f"{API}/vehicles/{v2['id']}/restore", headers=ctx["m"])).json()[
        "archived_at"
    ] is None
    # повторное архивирование/восстановление идемпотентно
    for _ in range(2):
        assert (
            await api.post(f"{API}/vehicles/{v2['id']}/restore", headers=ctx["m"])
        ).status_code == 200

    for action in ("create", "update", "archive", "restore"):
        assert await audit(db, "vehicle", action), action


@integration
async def test_duplicate_vin(api, ctx):
    a = await mk_client(api, ctx["m"])
    b = await mk_client(api, ctx["m"], full_name="Петров", phone="+79990000001")
    v = await mk_vehicle(api, ctx["m"], a["id"], vin=VIN1)
    r = await api.post(
        f"{API}/clients/{b['id']}/vehicles", headers=ctx["m"], json=vbody(vin=VIN1.lower())
    )
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "duplicate_vin"
    assert err["details"] == {"existing_vehicle_id": v["id"], "existing_client_id": a["id"]}

    # без VIN можно сколько угодно
    await mk_vehicle(api, ctx["m"], b["id"])
    await mk_vehicle(api, ctx["m"], b["id"])
    # смена VIN на занятый
    w = await mk_vehicle(api, ctx["m"], b["id"], vin=VIN2)
    r = await api.patch(f"{API}/vehicles/{w['id']}", headers=ctx["m"], json={"vin": VIN1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_vin"
    # собственный VIN допустим
    r = await api.patch(f"{API}/vehicles/{w['id']}", headers=ctx["m"], json={"vin": VIN2})
    assert r.status_code == 200

    # архивный VIN не блокирует; восстановление дубля — 409
    await api.post(f"{API}/vehicles/{v['id']}/archive", headers=ctx["m"])
    again = await api.post(
        f"{API}/clients/{b['id']}/vehicles", headers=ctx["m"], json=vbody(vin=VIN1)
    )
    assert again.status_code == 201
    r = await api.post(f"{API}/vehicles/{v['id']}/restore", headers=ctx["m"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_vin"


@integration
async def test_vehicle_validation_and_archived_client(api, ctx):
    c = await mk_client(api, ctx["m"])
    for bad in (
        {"vin": "XTA210990Y2766I89"},
        {"year": 1900},
        {"year": 2101},
        {"mileage": -1},
        {"plate_number": "ZZZ"},
        {"make": ""},
        {"client_id": str(uuid.uuid4())},
        {"archived_at": "2020-01-01T00:00:00Z"},
    ):
        r = await api.post(f"{API}/clients/{c['id']}/vehicles", headers=ctx["m"], json=vbody(**bad))
        assert r.status_code == 422, bad
    await api.post(f"{API}/clients/{c['id']}/archive", headers=ctx["m"])
    r = await api.post(f"{API}/clients/{c['id']}/vehicles", headers=ctx["m"], json=vbody())
    assert r.status_code == 409 and r.json()["error"]["code"] == "client_archived"


@integration
async def test_not_found(api, ctx):
    ghost = uuid.uuid4()
    for method, url in [
        ("get", f"/clients/{ghost}"),
        ("patch", f"/clients/{ghost}"),
        ("post", f"/clients/{ghost}/archive"),
        ("post", f"/clients/{ghost}/restore"),
        ("get", f"/clients/{ghost}/vehicles"),
        ("post", f"/clients/{ghost}/vehicles"),
        ("get", f"/vehicles/{ghost}"),
        ("patch", f"/vehicles/{ghost}"),
        ("post", f"/vehicles/{ghost}/archive"),
        ("post", f"/vehicles/{ghost}/restore"),
    ]:
        kw = {"json": vbody() if method == "post" and url.endswith("vehicles") else {}}
        r = await api.request(method.upper(), f"{API}{url}", headers=ctx["m"], **kw)
        assert r.status_code == 404, (method, url, r.text)
    assert (await api.get(f"{API}/clients/not-a-uuid", headers=ctx["m"])).status_code == 422


@integration
async def test_archive_restore_client_and_list_filters(api, db, ctx):
    a = await mk_client(api, ctx["m"], full_name="Алексеев", source="walk_in")
    b = await mk_client(
        api, ctx["m"], full_name="Борисов", phone="+79990000002", client_type="company"
    )
    r = await api.post(f"{API}/clients/{a['id']}/archive", headers=ctx["m"])
    assert r.status_code == 200 and r.json()["archived_at"] is not None
    assert (await api.post(f"{API}/clients/{a['id']}/archive", headers=ctx["m"])).status_code == 200

    lst = (await api.get(f"{API}/clients", headers=ctx["m"])).json()
    assert [c["id"] for c in lst["items"]] == [b["id"]] and lst["total"] == 1
    arch = (await api.get(f"{API}/clients", headers=ctx["m"], params={"archived": True})).json()
    assert [c["id"] for c in arch["items"]] == [a["id"]]
    comp = (
        await api.get(f"{API}/clients", headers=ctx["m"], params={"client_type": "company"})
    ).json()
    assert comp["total"] == 1
    assert (await api.get(f"{API}/clients", headers=ctx["m"], params={"source": "ads"})).json()[
        "total"
    ] == 0

    r = await api.post(f"{API}/clients/{a['id']}/restore", headers=ctx["m"])
    assert r.status_code == 200 and r.json()["archived_at"] is None
    assert (await api.get(f"{API}/clients", headers=ctx["m"])).json()["total"] == 2
    # архивный клиент доступен по id
    for action in ("create", "archive", "restore"):
        assert await audit(db, "client", action), action


@integration
async def test_pagination_limits(api, ctx):
    for i in range(3):
        await mk_client(api, ctx["m"], full_name=f"Клиент {i}", phone=f"+7999000010{i}")
    page = (await api.get(f"{API}/clients", headers=ctx["m"], params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["total"] == 3
    page2 = (
        await api.get(f"{API}/clients", headers=ctx["m"], params={"limit": 2, "offset": 2})
    ).json()
    assert len(page2["items"]) == 1
    for params in (
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"offset": 1_000_001},
        {"limit": "x"},
    ):
        r = await api.get(f"{API}/clients", headers=ctx["m"], params=params)
        assert r.status_code == 422, params


# ---------------- поиск ----------------


@pytest.fixture
async def data(api, ctx):
    ivan = await mk_client(api, ctx["m"], full_name="Иванов Пётр", phone="+79161234567")
    comp = await mk_client(
        api, ctx["m"], client_type="company", full_name="Сидоров", company_name="ООО Вектор-Авто",
        phone="+79269990000",
    )  # fmt: skip
    car = await mk_vehicle(
        api, ctx["m"], ivan["id"], vin=VIN1, plate_number="А123ВС77", make="Toyota", model="Camry"
    )
    return {"ivan": ivan, "comp": comp, "car": car}


async def ids(api, h, **params):
    r = await api.get(f"{API}/clients", headers=h, params=params)
    assert r.status_code == 200, r.text
    return {c["id"] for c in r.json()["items"]}


@integration
async def test_search_by_name_phone_company_plate_vin(api, ctx, data):
    h, ivan, comp = ctx["m"], data["ivan"]["id"], data["comp"]["id"]
    assert await ids(api, h, search="иван") == {ivan}  # регистр, кириллица
    assert await ids(api, h, search="ИВАНОВ пёТР") == {ivan}
    assert await ids(api, h, search="4567") == {ivan}  # последние цифры
    assert await ids(api, h, search="+7 916 123-45-67") == {ivan}
    assert await ids(api, h, search="8 (916) 123 45 67") == {ivan}
    assert await ids(api, h, search="вектор") == {comp}
    assert await ids(api, h, search="а123вс") == {ivan}  # кириллица, нижний регистр
    assert await ids(api, h, search="a123bc77") == {ivan}  # латиница
    assert await ids(api, h, search="A 123 BC") == {ivan}
    assert await ids(api, h, search="210990y2") == {ivan}  # часть VIN, нижний регистр
    assert await ids(api, h, search="zzz-нет-такого") == set()
    assert await ids(api, h) == {ivan, comp}
    assert await ids(api, h, search="   ") == {ivan, comp}


@integration
async def test_search_total_and_vehicles_count_in_list(api, ctx, data):
    r = (await api.get(f"{API}/clients", headers=ctx["m"], params={"search": "ivan"})).json()
    assert r["total"] == 0
    r = (await api.get(f"{API}/clients", headers=ctx["m"], params={"search": "Иван"})).json()
    assert r["total"] == 1 and r["items"][0]["vehicles_count"] == 1


@integration
@pytest.mark.parametrize(
    "term, expected",
    [
        ("%", 0),
        ("_", 0),
        ("\\", 0),
        ("Иван%", 0),
        ("И_анов", 0),
        ("%%%%", 0),
        ("'", 0),
        ("''", 0),
        ("' OR 1=1 --", 0),
        ("'; DROP TABLE clients;--", 0),
        ("1' UNION SELECT NULL--", 0),
        ("Иван\x00ов", 1),  # NUL удаляется, остаётся «Иванов»
        ("\x00", 2),  # после очистки пусто → без фильтра
    ],
)
async def test_search_special_characters(api, ctx, data, term, expected):
    r = await api.get(f"{API}/clients", headers=ctx["m"], params={"search": term})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == expected
    # таблицы целы
    assert (await api.get(f"{API}/clients", headers=ctx["m"])).json()["total"] == 2


@integration
async def test_search_literal_percent_and_underscore_match_only_literally(api, ctx):
    a = await mk_client(api, ctx["m"], full_name="Скидка 100% Клиент", phone="+79990001111")
    b = await mk_client(api, ctx["m"], full_name="Иван_Петров", phone="+79990002222")
    await mk_client(api, ctx["m"], full_name="Ивану Петровичу", phone="+79990003333")
    assert await ids(api, ctx["m"], search="100%") == {a["id"]}
    assert await ids(api, ctx["m"], search="Иван_П") == {b["id"]}


@integration
async def test_search_oversize_and_payloads(api, ctx, data):
    r = await api.get(f"{API}/clients", headers=ctx["m"], params={"search": "A" * 101})
    assert r.status_code == 422
    for payload in ALL:
        if len(payload) > 100:
            continue
        r = await api.get(f"{API}/clients", headers=ctx["m"], params={"search": payload})
        assert r.status_code == 200, (payload, r.text)
        r = await api.get(f"{API}/search", headers=ctx["m"], params={"q": payload})
        assert r.status_code in (200, 422), (payload, r.text)


@integration
async def test_global_search(api, ctx, data):
    h = ctx["m"]
    r = await api.get(f"{API}/search", headers=h, params={"q": "иванов"})
    assert r.status_code == 200
    assert r.json() == [
        {
            "type": "client",
            "id": data["ivan"]["id"],
            "title": "Иванов Пётр",
            "subtitle": "+79161234567",
            "client_id": data["ivan"]["id"],
        }
    ]
    r = await api.get(f"{API}/search", headers=h, params={"q": "a123bc"})
    assert {h_["type"] for h_ in r.json()} == {"client", "vehicle"}
    veh = next(x for x in r.json() if x["type"] == "vehicle")
    assert veh == {
        "type": "vehicle",
        "id": data["car"]["id"],
        "title": "Toyota Camry",
        "subtitle": "А123ВС77",
        "client_id": data["ivan"]["id"],
    }
    r = await api.get(f"{API}/search", headers=h, params={"q": "camry"})
    assert [x["type"] for x in r.json()] == ["vehicle"]
    r = await api.get(f"{API}/search", headers=h, params={"q": "XTA2109"})
    assert any(x["type"] == "vehicle" for x in r.json())
    # архивные не попадают в поиск
    await api.post(f"{API}/vehicles/{data['car']['id']}/archive", headers=h)
    assert (await api.get(f"{API}/search", headers=h, params={"q": "camry"})).json() == []


@integration
async def test_global_search_validation_and_limit(api, ctx):
    h = ctx["m"]
    for params in (
        {},
        {"q": ""},
        {"q": "a"},
        {"q": " a "},
        {"q": "a\x00"},
        {"q": "ab", "limit": 0},
        {"q": "ab", "limit": 51},
        {"q": "x" * 101},
    ):
        r = await api.get(f"{API}/search", headers=h, params=params)
        assert r.status_code == 422, params
        assert r.json()["error"]["code"] == "validation_error"
    for i in range(4):
        c = await mk_client(api, h, full_name=f"Маша {i}", phone=f"+7999000020{i}")
        await mk_vehicle(api, h, c["id"], make="Маша-мобиль", model=str(i))
    r = await api.get(f"{API}/search", headers=h, params={"q": "маша", "limit": 3})
    assert len(r.json()) == 3
    r = await api.get(f"{API}/search", headers=h, params={"q": "%_"})
    assert r.status_code == 200 and r.json() == []
    r = await api.get(f"{API}/search", headers=h, params={"q": "' OR 1=1 --"})
    assert r.status_code == 200 and r.json() == []


# ---------------- права ----------------

ENDPOINTS = [
    ("GET", "/clients", None),
    ("POST", "/clients", cbody()),
    ("GET", "/clients/{c}", None),
    ("PATCH", "/clients/{c}", {"notes": "x"}),
    ("POST", "/clients/{c}/archive", None),
    ("POST", "/clients/{c}/restore", None),
    ("GET", "/clients/{c}/vehicles", None),
    ("POST", "/clients/{c}/vehicles", vbody()),
    ("GET", "/vehicles/{v}", None),
    ("PATCH", "/vehicles/{v}", {"color": "красный"}),
    ("POST", "/vehicles/{v}/archive", None),
    ("POST", "/vehicles/{v}/restore", None),
    ("GET", "/search?q=ab", None),
]


@integration
@pytest.mark.parametrize("method, path, body", ENDPOINTS)
async def test_permissions(api, ctx, method, path, body):
    c = await mk_client(api, ctx["m"], phone="+79990009999")
    v = await mk_vehicle(api, ctx["m"], c["id"])
    path = f"{API}{path.format(c=c['id'], v=v['id'])}"

    for who in ("m", "d"):
        r = await api.request(method, path, headers=ctx[who], json=body)
        assert r.status_code in (200, 201, 409), (who, r.status_code, r.text)

    r = await api.request(method, path, headers=ctx["x"], json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"

    r = await api.request(method, path, json=body)
    assert r.status_code == 401
    r = await api.request(method, path, headers=bearer("garbage"), json=body)
    assert r.status_code == 401


@integration
async def test_clients_shared_between_managers_of_different_locations(api, db, ctx):
    other_loc = await make_location(db, "Вторая")
    other = await make_user(db, Role.manager, locations=[other_loc])
    h2 = bearer(await login(api, other))
    c = await mk_client(api, ctx["m"])
    r = await api.get(f"{API}/clients/{c['id']}", headers=h2)
    assert r.status_code == 200


# ---------------- инъекции во все текстовые поля ----------------


def _neutral(value):
    if isinstance(value, str):
        assert "\x00" not in value and "<" not in value and ">" not in value, value


@integration
@pytest.mark.parametrize("payload", ALL)
@pytest.mark.parametrize(
    "field",
    ["full_name", "company_name", "notes", "email", "phone", "phone_extra", "inn", "source"],
)
async def test_client_fields_injection(api, db, ctx, field, payload):
    r = await api.post(f"{API}/clients", headers=ctx["m"], json=cbody(**{field: payload}))
    assert r.status_code in (201, 422), (field, r.status_code)
    assert r.status_code != 500
    if r.status_code == 201:
        for v in r.json().values():
            _neutral(v)
        got = (await api.get(f"{API}/clients/{r.json()['id']}", headers=ctx["m"])).json()
        for v in got.values():
            _neutral(v)
    else:
        assert payload not in r.text or len(payload) < 3
    assert (await api.get(f"{API}/clients", headers=ctx["m"])).status_code == 200


@integration
@pytest.mark.parametrize("payload", ALL)
@pytest.mark.parametrize(
    "field", ["make", "model", "color", "notes", "vin", "plate_number", "year", "mileage"]
)
async def test_vehicle_fields_injection(api, ctx, field, payload):
    c = await mk_client(api, ctx["m"])
    r = await api.post(
        f"{API}/clients/{c['id']}/vehicles", headers=ctx["m"], json=vbody(**{field: payload})
    )
    assert r.status_code in (201, 422), (field, r.status_code)
    if r.status_code == 201:
        for v in r.json().values():
            _neutral(v)
    # то же через PATCH
    v = await mk_vehicle(api, ctx["m"], c["id"])
    r = await api.patch(f"{API}/vehicles/{v['id']}", headers=ctx["m"], json={field: payload})
    assert r.status_code in (200, 422), (field, r.status_code)
    if r.status_code == 200:
        for val in r.json().values():
            _neutral(val)


@integration
@pytest.mark.parametrize("payload", ALL)
async def test_client_patch_injection(api, ctx, payload):
    c = await mk_client(api, ctx["m"])
    r = await api.patch(f"{API}/clients/{c['id']}", headers=ctx["m"], json={"notes": payload})
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        _neutral(r.json()["notes"])
