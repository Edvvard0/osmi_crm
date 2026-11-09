"""Модуль 3: каталог услуг, цены по точкам, посты, запчасти — API, права, дубли, поиск, инъекции."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.schemas.catalog import PartCreate, PartUpdate, ServiceCreate, ServiceUpdate
from tests.factories import bearer, login, make_location, make_user
from tests.security.payloads import ALL, MARKUP

API = "/api/v1"

integration = pytest.mark.integration

# ---------------- unit: схемы (без БД) ----------------


def sbody(category_id=None, /, **kw):
    base = {
        "category_id": str(category_id or uuid.uuid4()),
        "code": "TO-1",
        "name": "Замена масла",
        "unit": "pcs",
        "base_price": "1500.00",
        "duration_minutes": 30,
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    "bad",
    [
        {"base_price": "-0.01"},
        {"base_price": "10.001"},
        {"base_price": "1e12"},
        {"base_price": "1234567890123"},
        {"base_price": "NaN"},
        {"base_price": "Infinity"},
        {"base_price": "abc"},
        {"base_price": None},
        {"norm_hours": "-1"},
        {"norm_hours": "1000.00"},
        {"norm_hours": "1.234"},
        {"duration_minutes": 0},
        {"duration_minutes": -5},
        {"duration_minutes": 1.5},
        {"duration_minutes": 10_081},
        {"unit": "kg"},
        {"code": "with space"},
        {"code": "A" * 21},
        {"code": ""},
        {"name": "  "},
    ],
)
def test_service_schema_rejects(bad):
    with pytest.raises(ValueError):
        ServiceCreate(**sbody(**bad))


def test_service_schema_normalizes():
    s = ServiceCreate(**sbody(base_price=1500, norm_hours="", description="  "))
    assert str(s.base_price) == "1500" and s.norm_hours is None and s.description is None
    assert ServiceUpdate(norm_hours=None).model_dump(exclude_unset=True) == {"norm_hours": None}
    for field in ("name", "unit", "base_price", "duration_minutes", "is_active"):
        with pytest.raises(ValueError):
            ServiceUpdate(**{field: None})


def test_part_schema():
    p = PartCreate(sku="A-1", name="Фильтр", barcode="  ", brand="", unit="pcs",
                   department="both", sale_price="10")  # fmt: skip
    assert p.barcode is None and p.brand is None
    with pytest.raises(ValueError):
        PartCreate(sku="A 1", name="x", unit="pcs", department="both", sale_price="1")
    with pytest.raises(ValueError):
        PartUpdate(sku="A-2")  # sku не меняется
    with pytest.raises(ValueError):
        PartUpdate(name=None)


# ---------------- интеграционные фикстуры ----------------


@pytest.fixture
async def ctx(api, db):
    loc_a = await make_location(db, "Точка А")
    loc_b = await make_location(db, "Точка Б")
    manager = await make_user(db, Role.manager, locations=[loc_a])
    manager_b = await make_user(db, Role.manager, locations=[loc_b])
    director = await make_user(db, Role.director)
    mechanic = await make_user(db, Role.mechanic, locations=[loc_a])
    return {
        "a": loc_a,
        "b": loc_b,
        "m": bearer(await login(api, manager)),
        "mb": bearer(await login(api, manager_b)),
        "d": bearer(await login(api, director)),
        "x": bearer(await login(api, mechanic)),
        "director": director,
    }


async def mk_cat(api, h, name="ТО", department="service", **kw):
    r = await api.post(
        f"{API}/service-categories",
        headers=h,
        json={"name": name, "department": department, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def mk_service(api, h, category_id, **kw):
    r = await api.post(f"{API}/services", headers=h, json=sbody(category_id, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def pbody(**kw):
    base = {
        "sku": "OF-100",
        "name": "Масляный фильтр",
        "unit": "pcs",
        "department": "service",
        "sale_price": "450.00",
    }
    return {**base, **kw}


async def mk_part(api, h, **kw):
    r = await api.post(f"{API}/parts", headers=h, json=pbody(**kw))
    assert r.status_code == 201, r.text
    return r.json()


async def mk_post(api, h, loc, name="Подъёмник 1", **kw):
    body = {"name": name, "post_type": "lift", "department": "service", **kw}
    r = await api.post(f"{API}/locations/{loc.id}/posts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def audit(db, entity_type, action=None):
    q = select(AuditLog).where(AuditLog.entity_type == entity_type)
    if action:
        q = q.where(AuditLog.action == action)
    return list(await db.scalars(q.order_by(AuditLog.id)))


# ---------------- права ----------------


@integration
async def test_unauthenticated_is_401(api):
    ghost = uuid.uuid4()
    for method, url in [
        ("GET", "/service-categories"),
        ("POST", "/service-categories"),
        ("GET", "/services"),
        ("GET", f"/services/{ghost}"),
        ("GET", f"/service-prices?location_id={ghost}"),
        ("PUT", f"/services/{ghost}/prices/{ghost}"),
        ("GET", f"/locations/{ghost}/posts"),
        ("PATCH", f"/posts/{ghost}"),
        ("GET", "/parts"),
        ("PATCH", f"/parts/{ghost}"),
    ]:
        r = await api.request(method, f"{API}{url}", json={})
        assert r.status_code == 401, (method, url)


@integration
async def test_permission_matrix(api, ctx):
    d, m, x = ctx["d"], ctx["m"], ctx["x"]
    loc = ctx["a"].id
    cat = await mk_cat(api, d)
    svc = await mk_service(api, d, cat["id"])
    part = await mk_part(api, d)
    post = await mk_post(api, d, ctx["a"])
    # (метод, url, тело, ожидание для director, manager, mechanic)
    POST_BODY = {"name": "П2", "post_type": "wash", "department": "service"}  # noqa: N806
    cases = [
        ("GET", "/service-categories", None, 200, 200, 403),
        ("POST", "/service-categories", {"name": "Новая", "department": "service"}, 201, 403, 403),
        ("PATCH", f"/service-categories/{cat['id']}", {"sort_order": 3}, 200, 403, 403),
        ("GET", f"/services?location_id={loc}", None, 200, 200, 403),
        ("GET", f"/services/{svc['id']}?location_id={loc}", None, 200, 200, 403),
        ("POST", "/services", sbody(cat["id"], code="NEW-1"), 201, 403, 403),
        ("PATCH", f"/services/{svc['id']}", {"name": "Другое"}, 200, 403, 403),
        ("GET", f"/service-prices?location_id={loc}", None, 200, 403, 403),
        ("GET", f"/services/{svc['id']}/prices", None, 200, 403, 403),
        ("PUT", f"/services/{svc['id']}/prices/{loc}", {"price": "1.00"}, 200, 403, 403),
        ("DELETE", f"/services/{svc['id']}/prices/{loc}", None, 204, 403, 403),
        ("GET", f"/locations/{loc}/posts", None, 200, 200, 200),
        ("POST", f"/locations/{loc}/posts", POST_BODY, 201, 403, 403),
        ("PATCH", f"/posts/{post['id']}", {"sort_order": 2}, 200, 403, 403),
        ("GET", "/parts", None, 200, 200, 403),
        ("POST", "/parts", pbody(sku="NEW-1"), 201, 403, 403),
        ("PATCH", f"/parts/{part['id']}", {"name": "Другое"}, 200, 403, 403),
    ]  # fmt: skip
    for method, url, body, ed, em, ex in cases:
        for h, expected in ((d, ed), (m, em), (x, ex)):
            kw = {"json": body} if body is not None else {}
            r = await api.request(method, f"{API}{url}", headers=h, **kw)
            assert r.status_code == expected, (method, url, h is d, h is m, r.text)
            if expected == 403:
                assert r.json()["error"]["code"] == "forbidden"


@integration
async def test_manager_cannot_change_anything_even_on_own_location(api, db, ctx):
    cat = await mk_cat(api, ctx["d"])
    svc = await mk_service(api, ctx["d"], cat["id"])
    r = await api.put(
        f"{API}/services/{svc['id']}/prices/{ctx['a'].id}",
        headers=ctx["m"],
        json={"price": "1.00"},
    )
    assert r.status_code == 403
    assert (
        await api.get(f"{API}/service-prices?location_id={ctx['a'].id}", headers=ctx["d"])
    ).json() == []
    assert await audit(db, "service_price") == []


# ---------------- категории ----------------


@integration
async def test_category_crud_shape_and_ordering(api, db, ctx):
    d = ctx["d"]
    c = await mk_cat(api, d, "Диагностика", sort_order=5)
    assert set(c) == {"id", "name", "department", "sort_order", "is_active"}
    assert c["is_active"] is True and c["sort_order"] == 5
    b = await mk_cat(api, d, "Бета", sort_order=1)
    p = await mk_cat(api, d, "Полировка", department="detailing")
    assert (await mk_cat(api, d, "Без порядка"))["sort_order"] == 0

    lst = (await api.get(f"{API}/service-categories", headers=ctx["m"])).json()
    assert [x["name"] for x in lst] == [
        "Полировка",
        "Без порядка",
        "Бета",
        "Диагностика",
    ]  # отдел, порядок, имя
    only = (await api.get(f"{API}/service-categories?department=detailing", headers=d)).json()
    assert [x["id"] for x in only] == [p["id"]]

    r = await api.patch(
        f"{API}/service-categories/{b['id']}",
        headers=d,
        json={"name": "Бета 2", "sort_order": 9, "is_active": False},
    )
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["name"] == "Бета 2"
    assert [
        x["id"]
        for x in (await api.get(f"{API}/service-categories?is_active=false", headers=d)).json()
    ] == [b["id"]]
    active = (await api.get(f"{API}/service-categories?is_active=true", headers=d)).json()
    assert b["id"] not in {x["id"] for x in active}  # fmt: skip

    for action in ("create", "update"):
        assert await audit(db, "service_category", action), action
    rows = await audit(db, "service_category", "update")
    assert rows[-1].changes["is_active"] == {"old": True, "new": False}
    assert rows[-1].user_id == ctx["director"].id
    # без изменений — без записи
    n = len(rows)
    await api.patch(f"{API}/service-categories/{b['id']}", headers=d, json={"sort_order": 9})
    assert len(await audit(db, "service_category", "update")) == n


@integration
async def test_category_duplicates(api, ctx):
    d = ctx["d"]
    first = await mk_cat(api, d, "ТО")
    r = await api.post(
        f"{API}/service-categories", headers=d, json={"name": "ТО", "department": "service"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    assert "uq_" not in r.text and "INSERT" not in r.text
    # то же имя в другом отделе — можно
    await mk_cat(api, d, "ТО", department="detailing")
    # переименование в занятое имя
    other = await mk_cat(api, d, "Другая")
    r = await api.patch(f"{API}/service-categories/{other['id']}", headers=d, json={"name": "ТО"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    # после ошибки всё работает
    assert (await api.get(f"{API}/service-categories", headers=d)).status_code == 200
    assert first["id"]


@integration
@pytest.mark.parametrize(
    "body",
    [
        {"name": "A", "department": "other"},
        {"name": "", "department": "service"},
        {"name": "A" * 101, "department": "service"},
        {"name": "A", "department": "service", "sort_order": -1},
        {"name": "A", "department": "service", "sort_order": 40000},
        {"name": "A", "department": "service", "is_active": False},
        {"name": "A", "department": "service", "id": str(uuid.uuid4())},
        {"department": "service"},
        {"name": 5, "department": "service"},
    ],
)
async def test_category_create_validation(api, ctx, body):
    r = await api.post(f"{API}/service-categories", headers=ctx["d"], json=body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


@integration
async def test_category_patch_rules(api, ctx):
    d = ctx["d"]
    c = await mk_cat(api, d)
    for body in (
        {"department": "detailing"},  # отдел не меняется
        {"id": str(uuid.uuid4())},
        {"name": None},
        {"is_active": None},
        {"sort_order": "x"},
    ):
        r = await api.patch(f"{API}/service-categories/{c['id']}", headers=d, json=body)
        assert r.status_code == 422, body
    r = await api.patch(f"{API}/service-categories/{uuid.uuid4()}", headers=d, json={"name": "Z"})
    assert r.status_code == 404
    r = await api.patch(f"{API}/service-categories/not-a-uuid", headers=d, json={})
    assert r.status_code == 422
    assert (
        await api.get(f"{API}/service-categories?department=nope", headers=d)
    ).status_code == 422


# ---------------- услуги ----------------


@integration
async def test_service_create_shape_money_strings_and_department(api, db, ctx):
    d = ctx["d"]
    svc_cat = await mk_cat(api, d, "ТО")
    det_cat = await mk_cat(api, d, "Полировка", department="detailing")
    s = await mk_service(
        api,
        d,
        svc_cat["id"],
        description="Масло и фильтр",
        base_price="1500",
        norm_hours="1.5",
    )
    assert set(s) == {
        "id", "category_id", "code", "name", "description", "department", "unit", "base_price",
        "norm_hours", "duration_minutes", "is_active", "price",
    }  # fmt: skip
    assert s["base_price"] == "1500.00" and s["price"] == "1500.00" and s["norm_hours"] == "1.50"
    assert s["department"] == "service" and s["is_active"] is True
    assert s["duration_minutes"] == 30 and s["description"] == "Масло и фильтр"

    p = await mk_service(api, d, det_cat["id"], code="POL-1", base_price=2999.5)
    assert p["department"] == "detailing" and p["base_price"] == "2999.50"
    assert p["norm_hours"] == "0.00" and p["description"] is None  # значения по умолчанию

    # department из тела не принимается
    r = await api.post(
        f"{API}/services", headers=d, json=sbody(svc_cat["id"], code="X1", department="detailing")
    )
    assert r.status_code == 422

    r = await api.post(
        f"{API}/services", headers=d, json=sbody(svc_cat["id"], code="X2", norm_hours=None)
    )
    assert r.status_code == 201 and r.json()["norm_hours"] == "0.00"

    got = (await api.get(f"{API}/services/{s['id']}", headers=d)).json()
    assert got == s
    rows = await audit(db, "service", "create")
    assert any(
        str(a.entity_id) == s["id"] and a.changes["base_price"]["new"] == "1500.00" for a in rows
    )


@integration
@pytest.mark.parametrize(
    "bad",
    [
        {"base_price": "-1"},
        {"base_price": "1.001"},
        {"base_price": "NaN"},
        {"base_price": "abc"},
        {"norm_hours": "-0.5"},
        {"duration_minutes": 0},
        {"duration_minutes": -1},
        {"unit": "box"},
        {"code": "BAD CODE"},
        {"name": ""},
        {"is_active": False},
        {"id": str(uuid.uuid4())},
        {"price": "1.00"},
        {"category_id": "nope"},
    ],
)
async def test_service_create_validation(api, ctx, bad):
    cat = await mk_cat(api, ctx["d"])
    r = await api.post(f"{API}/services", headers=ctx["d"], json=sbody(cat["id"], **bad))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


@integration
async def test_service_missing_category_is_422_and_missing_fields(api, ctx):
    r = await api.post(f"{API}/services", headers=ctx["d"], json=sbody(uuid.uuid4()))
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"category_id": "not_found"}
    r = await api.post(f"{API}/services", headers=ctx["d"], json={"name": "x"})
    assert r.status_code == 422


@integration
async def test_service_duplicate_code(api, ctx):
    d = ctx["d"]
    cat = await mk_cat(api, d)
    other_cat = await mk_cat(api, d, "Ещё", department="detailing")
    s = await mk_service(api, d, cat["id"], code="DUP-1")
    for category in (cat, other_cat):  # код уникален во всём каталоге
        r = await api.post(
            f"{API}/services", headers=d, json=sbody(category["id"], code="DUP-1", name="Другая")
        )
        assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    assert (await api.get(f"{API}/services/{s['id']}", headers=d)).status_code == 200
    # code не меняется через PATCH
    r = await api.patch(f"{API}/services/{s['id']}", headers=d, json={"code": "NEW"})
    assert r.status_code == 422


@integration
async def test_service_patch_and_deactivation(api, db, ctx):
    d = ctx["d"]
    cat = await mk_cat(api, d)
    other = await mk_cat(api, d, "Другая")
    s = await mk_service(api, d, cat["id"], description="старое", norm_hours="2")
    r = await api.patch(
        f"{API}/services/{s['id']}",
        headers=d,
        json={
            "name": "Новое имя",
            "description": None,
            "unit": "hour",
            "base_price": "1999.9",
            "norm_hours": "0.75",
            "duration_minutes": 45,
        },
    )
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["name"] == "Новое имя" and u["description"] is None and u["unit"] == "hour"
    assert u["base_price"] == "1999.90" and u["price"] == "1999.90" and u["norm_hours"] == "0.75"
    assert u["duration_minutes"] == 45 and u["code"] == s["code"]

    # норма-часы null → 0
    r = await api.patch(f"{API}/services/{s['id']}", headers=d, json={"norm_hours": None})
    assert r.status_code == 200 and r.json()["norm_hours"] == "0.00"

    # деактивация вместо удаления
    r = await api.patch(f"{API}/services/{s['id']}", headers=d, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (await api.delete(f"{API}/services/{s['id']}", headers=d)).status_code == 405
    inactive = (await api.get(f"{API}/services?is_active=false", headers=d)).json()
    assert [x["id"] for x in inactive["items"]] == [s["id"]]
    assert (await api.get(f"{API}/services?is_active=true", headers=d)).json()["total"] == 0

    for bad in (
        {"category_id": other["id"]},
        {"department": "detailing"},
        {"id": str(uuid.uuid4())},
        {"price": "1.00"},
        {"name": None},
        {"base_price": None},
        {"base_price": "-1"},
        {"duration_minutes": 0},
    ):
        r = await api.patch(f"{API}/services/{s['id']}", headers=d, json=bad)
        assert r.status_code == 422, bad
    assert (
        await api.patch(f"{API}/services/{uuid.uuid4()}", headers=d, json={"name": "x"})
    ).status_code == 404

    rows = await audit(db, "service", "update")
    assert rows[0].changes["base_price"] == {"old": "1500.00", "new": "1999.90"}
    assert rows[0].changes["description"] == {"old": "старое", "new": None}
    assert rows[-1].changes == {"is_active": {"old": True, "new": False}}


@integration
async def test_service_list_filters_search_and_pagination(api, ctx):
    d = ctx["d"]
    c1 = await mk_cat(api, d, "ТО")
    c2 = await mk_cat(api, d, "Полировка", department="detailing")
    await mk_service(api, d, c1["id"], code="A-01", name="Замена масла")
    await mk_service(api, d, c1["id"], code="A-02", name="Замена колодок")
    await mk_service(api, d, c2["id"], code="B-01", name="Полировка кузова")
    off = await mk_service(api, d, c2["id"], code="B-02", name="Нано-керамика")
    await api.patch(f"{API}/services/{off['id']}", headers=d, json={"is_active": False})

    def names(page):
        return [i["code"] for i in page["items"]]

    allp = (await api.get(f"{API}/services", headers=d)).json()
    assert allp["total"] == 4 and names(allp) == ["A-01", "A-02", "B-01", "B-02"]
    q = lambda **p: api.get(f"{API}/services", headers=d, params=p)  # noqa: E731
    assert names((await q(category_id=c2["id"])).json()) == ["B-01", "B-02"]
    assert names((await q(department="service")).json()) == ["A-01", "A-02"]
    assert names((await q(is_active="true")).json()) == ["A-01", "A-02", "B-01"]
    assert names((await q(search="ЗАМЕНА")).json()) == ["A-01", "A-02"]  # регистр, кириллица
    assert names((await q(search="b-0")).json()) == ["B-01", "B-02"]  # по коду
    assert names((await q(search="масл", department="service")).json()) == ["A-01"]
    assert (await q(search="нет такого")).json() == {"items": [], "total": 0}

    p1 = (await q(limit=3)).json()
    p2 = (await q(limit=3, offset=3)).json()
    assert p1["total"] == p2["total"] == 4 and len(p1["items"]) == 3 and names(p2) == ["B-02"]
    assert (await q(offset=100)).json() == {"items": [], "total": 4}
    for params in (
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"limit": "x"},
        {"search": "A" * 101},
        {"category_id": "nope"},
        {"department": "both"},
        {"is_active": "maybe"},
    ):
        assert (await q(**params)).status_code == 422, params
    assert (await q(limit=200)).status_code == 200


@integration
async def test_service_search_special_characters(api, ctx):
    d = ctx["d"]
    cat = await mk_cat(api, d)
    a = await mk_service(api, d, cat["id"], code="P-1", name="Скидка 100% на всё")
    b = await mk_service(api, d, cat["id"], code="P_2", name="Мойка_экспресс")
    c = await mk_service(api, d, cat["id"], code="P-3", name="Мойка экспресс")
    e = await mk_service(api, d, cat["id"], code="P-4", name="О'Нил сервис")
    await mk_service(api, d, cat["id"], code="P-5", name="Обычная")

    async def ids(term):
        r = await api.get(f"{API}/services", headers=d, params={"search": term})
        assert r.status_code == 200, (term, r.text)
        return {i["id"] for i in r.json()["items"]}

    assert await ids("100%") == {a["id"]}
    assert await ids("%") == {a["id"]}
    assert await ids("а_э") == {b["id"]}  # «_» — обычный символ, не маска
    assert await ids("P_2") == {b["id"]}
    assert await ids("'") == {e["id"]}
    assert await ids("\\") == set()
    assert await ids("' OR '1'='1") == set()
    assert await ids("'; DROP TABLE services;--") == set()
    assert await ids("Мойка") == {b["id"], c["id"]}
    # NUL удаляется: «Мой\x00ка» == «Мойка»; только NUL — фильтра нет
    assert await ids("Мой\x00ка") == {b["id"], c["id"]}
    assert len(await ids("\x00")) == 5
    for payload in ALL:
        if len(payload) <= 100:
            r = await api.get(f"{API}/services", headers=d, params={"search": payload})
            assert r.status_code == 200, payload
    assert (await api.get(f"{API}/services", headers=d)).json()["total"] == 5


# ---------------- эффективная цена ----------------


@integration
async def test_effective_price_override_base_and_reset(api, db, ctx):
    d, m, mb = ctx["d"], ctx["m"], ctx["mb"]
    a, b = ctx["a"].id, ctx["b"].id
    cat = await mk_cat(api, d)
    s = await mk_service(api, d, cat["id"], base_price="1000.00")
    sid = s["id"]
    other = await mk_service(api, d, cat["id"], code="TO-2", base_price="500.00")

    async def price(h, loc=None, one=False):
        params = {"location_id": str(loc)} if loc else {}
        if one:
            return (await api.get(f"{API}/services/{sid}", headers=h, params=params)).json()[
                "price"
            ]
        items = (await api.get(f"{API}/services", headers=h, params=params)).json()["items"]
        return {i["code"]: i["price"] for i in items}["TO-1"]

    # переопределения нет — базовая
    assert await price(m, a) == "1000.00" and await price(m, a, one=True) == "1000.00"

    r = await api.put(f"{API}/services/{sid}/prices/{a}", headers=d, json={"price": "1200"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"service_id", "location_id", "price", "updated_at"}
    assert (
        body["price"] == "1200.00" and body["service_id"] == sid and body["location_id"] == str(a)
    )

    # менеджер точки А видит цену точки, менеджер точки Б — базовую
    assert await price(m, a) == "1200.00" and await price(m, a, one=True) == "1200.00"
    assert await price(mb, b) == "1000.00" and await price(mb, b, one=True) == "1000.00"
    # руководитель: без точки — базовая, с точкой — переопределённая / базовая
    assert await price(d) == "1000.00" and await price(d, one=True) == "1000.00"
    assert await price(d, a) == "1200.00" and await price(d, b) == "1000.00"
    # base_price самой услуги не изменилась; другая услуга не затронута
    detail = (
        await api.get(f"{API}/services/{sid}", headers=d, params={"location_id": str(a)})
    ).json()
    assert detail["base_price"] == "1000.00" and detail["price"] == "1200.00"
    items = (await api.get(f"{API}/services", headers=m, params={"location_id": str(a)})).json()[
        "items"
    ]
    assert {i["id"]: i["price"] for i in items}[other["id"]] == "500.00"

    # обновление существующего переопределения (даже на ноль — это валидная цена)
    r = await api.put(f"{API}/services/{sid}/prices/{a}", headers=d, json={"price": "0.00"})
    assert r.status_code == 200 and r.json()["price"] == "0.00"
    assert await price(m, a) == "0.00"
    r = await api.put(f"{API}/services/{sid}/prices/{a}", headers=d, json={"price": "999.99"})
    assert r.json()["price"] == "999.99"
    assert len((await api.get(f"{API}/services/{sid}/prices", headers=d)).json()) == 1

    # удаление переопределения → базовая
    assert (await api.delete(f"{API}/services/{sid}/prices/{a}", headers=d)).status_code == 204
    assert await price(m, a) == "1000.00" and await price(m, a, one=True) == "1000.00"
    assert (await api.get(f"{API}/services/{sid}/prices", headers=d)).json() == []

    rows = await audit(db, "service_price")
    assert [r.action for r in rows] == ["create", "update", "update", "delete"]
    assert rows[0].changes == {"price": {"old": None, "new": "1200.00"}}
    assert rows[0].location_id == a and str(rows[0].entity_id) == sid
    assert rows[-1].changes == {"price": {"old": "999.99", "new": None}}


@integration
async def test_price_param_rules_by_role(api, ctx):
    d, m, x = ctx["d"], ctx["m"], ctx["x"]
    cat = await mk_cat(api, d)
    s = await mk_service(api, d, cat["id"])
    ghost = uuid.uuid4()
    # менеджер обязан передать точку
    for url in ("/services", f"/services/{s['id']}"):
        r = await api.get(f"{API}{url}", headers=m)
        assert r.status_code == 422, url
        assert r.json()["error"]["code"] == "validation_error"
        assert r.json()["error"]["fields"] == {"location_id": "missing"}
        # чужая и несуществующая точка — 404
        for loc in (ctx["b"].id, ghost):
            r = await api.get(f"{API}{url}", headers=m, params={"location_id": str(loc)})
            assert r.status_code == 404, (url, loc)
            assert r.json()["error"]["code"] == "not_found"
        r = await api.get(f"{API}{url}", headers=m, params={"location_id": "nope"})
        assert r.status_code == 422
        # механик — 403 в любом случае
        r = await api.get(f"{API}{url}", headers=x, params={"location_id": str(ctx["a"].id)})
        assert r.status_code == 403
    # руководитель: несуществующая точка — 404, сервис не найден — 404
    r = await api.get(f"{API}/services", headers=d, params={"location_id": str(ghost)})
    assert r.status_code == 404
    r = await api.get(
        f"{API}/services/{ghost}", headers=m, params={"location_id": str(ctx["a"].id)}
    )
    assert r.status_code == 404
    assert (await api.get(f"{API}/services/not-uuid", headers=d)).status_code == 422


@integration
async def test_manager_with_two_locations(api, db, ctx):
    d = ctx["d"]
    both = await make_user(db, Role.manager, locations=[ctx["a"], ctx["b"]])
    h = bearer(await login(api, both))
    cat = await mk_cat(api, d)
    s = await mk_service(api, d, cat["id"], base_price="100")
    await api.put(f"{API}/services/{s['id']}/prices/{ctx['b'].id}", headers=d, json={"price": "90"})
    for loc, expected in ((ctx["a"].id, "100.00"), (ctx["b"].id, "90.00")):
        r = await api.get(f"{API}/services/{s['id']}", headers=h, params={"location_id": str(loc)})
        assert r.json()["price"] == expected


@integration
async def test_price_endpoints_lists_and_errors(api, ctx):
    d = ctx["d"]
    a, b = ctx["a"].id, ctx["b"].id
    cat = await mk_cat(api, d)
    s1 = await mk_service(api, d, cat["id"], code="S1")
    s2 = await mk_service(api, d, cat["id"], code="S2")
    for sid, loc, price in ((s1["id"], a, "10"), (s1["id"], b, "11"), (s2["id"], a, "20.5")):
        r = await api.put(f"{API}/services/{sid}/prices/{loc}", headers=d, json={"price": price})
        assert r.status_code == 200

    on_a = (
        await api.get(f"{API}/service-prices", headers=d, params={"location_id": str(a)})
    ).json()
    assert {(p["service_id"], p["price"]) for p in on_a} == {
        (s1["id"], "10.00"),
        (s2["id"], "20.50"),
    }
    assert all(p["location_id"] == str(a) for p in on_a)
    of_s1 = (await api.get(f"{API}/services/{s1['id']}/prices", headers=d)).json()
    assert {(p["location_id"], p["price"]) for p in of_s1} == {(str(a), "10.00"), (str(b), "11.00")}

    ghost = uuid.uuid4()
    # location_id обязателен
    assert (await api.get(f"{API}/service-prices", headers=d)).status_code == 422
    assert (
        await api.get(f"{API}/service-prices", headers=d, params={"location_id": str(ghost)})
    ).status_code == 404
    assert (await api.get(f"{API}/services/{ghost}/prices", headers=d)).status_code == 404
    assert (
        await api.put(f"{API}/services/{ghost}/prices/{a}", headers=d, json={"price": "1"})
    ).status_code == 404
    assert (
        await api.put(f"{API}/services/{s1['id']}/prices/{ghost}", headers=d, json={"price": "1"})
    ).status_code == 404
    assert (await api.delete(f"{API}/services/{ghost}/prices/{a}", headers=d)).status_code == 404
    assert (
        await api.delete(f"{API}/services/{s1['id']}/prices/{ghost}", headers=d)
    ).status_code == 404
    # удаление несуществующего переопределения идемпотентно
    for _ in range(2):
        r = await api.delete(f"{API}/services/{s2['id']}/prices/{b}", headers=d)
        assert r.status_code == 204 and r.content == b""

    for bad in (
        {"price": "-1"},
        {"price": "1.234"},
        {"price": "NaN"},
        {"price": "abc"},
        {"price": None},
        {"price": "1e13"},
        {},
        {"price": "1", "service_id": str(s2["id"])},
        {"price": "1", "updated_at": "2020-01-01T00:00:00Z"},
    ):
        r = await api.put(f"{API}/services/{s1['id']}/prices/{a}", headers=d, json=bad)
        assert r.status_code == 422, bad
    # цена не изменилась после отклонённых запросов
    assert (await api.get(f"{API}/services/{s1['id']}/prices", headers=d)).json()[0]["price"] in {
        "10.00",
        "11.00",
    }


# ---------------- посты ----------------


@integration
async def test_posts_crud_and_visibility(api, db, ctx):
    d = ctx["d"]
    p1 = await mk_post(api, d, ctx["a"], "Подъёмник 1", sort_order=2)
    p2 = await mk_post(
        api, d, ctx["a"], "Бокс детейлинга", post_type="detailing_box", department="detailing"
    )
    await mk_post(api, d, ctx["b"], "Подъёмник 1")  # то же имя в другой точке — можно
    assert set(p1) == {
        "id",
        "location_id",
        "name",
        "post_type",
        "department",
        "sort_order",
        "is_active",
    }
    assert (
        p1["location_id"] == str(ctx["a"].id) and p1["is_active"] is True and p1["sort_order"] == 2
    )

    # порядок: sort_order, имя
    for h in (d, ctx["m"], ctx["x"]):
        lst = (await api.get(f"{API}/locations/{ctx['a'].id}/posts", headers=h)).json()
        assert [p["id"] for p in lst] == [p2["id"], p1["id"]]
    # директор видит все точки; менеджер/механик другой точки — 404
    assert len((await api.get(f"{API}/locations/{ctx['b'].id}/posts", headers=d)).json()) == 1
    for h in (ctx["m"], ctx["x"]):
        r = await api.get(f"{API}/locations/{ctx['b'].id}/posts", headers=h)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert (await api.get(f"{API}/locations/{uuid.uuid4()}/posts", headers=d)).status_code == 404
    assert (await api.get(f"{API}/locations/nope/posts", headers=d)).status_code == 422

    r = await api.patch(
        f"{API}/posts/{p1['id']}",
        headers=d,
        json={"name": "Подъёмник 1А", "post_type": "other", "department": "detailing",
              "sort_order": 0, "is_active": False},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["name"] == "Подъёмник 1А" and u["post_type"] == "other" and u["is_active"] is False
    assert u["department"] == "detailing" and u["location_id"] == p1["location_id"]
    only_active = (
        await api.get(f"{API}/locations/{ctx['a'].id}/posts?is_active=true", headers=ctx["m"])
    ).json()
    assert [p["id"] for p in only_active] == [p2["id"]]
    inactive = (
        await api.get(f"{API}/locations/{ctx['a'].id}/posts?is_active=false", headers=d)
    ).json()
    assert [p["id"] for p in inactive] == [p1["id"]]

    assert (
        await api.patch(f"{API}/posts/{uuid.uuid4()}", headers=d, json={"name": "Z"})
    ).status_code == 404
    assert (await audit(db, "work_post", "create"))[0].location_id == ctx["a"].id
    upd = await audit(db, "work_post", "update")
    assert upd[-1].changes["name"] == {"old": "Подъёмник 1", "new": "Подъёмник 1А"}
    assert upd[-1].location_id == ctx["a"].id


@integration
async def test_posts_create_rules(api, ctx):
    d = ctx["d"]
    p = await mk_post(api, d, ctx["a"], "Пост")
    r = await api.post(
        f"{API}/locations/{ctx['a'].id}/posts",
        headers=d,
        json={"name": "Пост", "post_type": "wash", "department": "service"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    # переименование в занятое имя
    q = await mk_post(api, d, ctx["a"], "Другой")
    r = await api.patch(f"{API}/posts/{q['id']}", headers=d, json={"name": "Пост"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    # несуществующая точка — 404
    r = await api.post(
        f"{API}/locations/{uuid.uuid4()}/posts",
        headers=d,
        json={"name": "П", "post_type": "wash", "department": "service"},
    )
    assert r.status_code == 404
    base = {"name": "Н", "post_type": "lift", "department": "service"}
    for bad in (
        {"post_type": "crane"},
        {"department": "both"},
        {"name": ""},
        {"name": "A" * 51},
        {"sort_order": -1},
        {"location_id": str(ctx["b"].id)},  # точка берётся из пути
        {"is_active": False},
        {"id": str(uuid.uuid4())},
    ):
        r = await api.post(f"{API}/locations/{ctx['a'].id}/posts", headers=d, json={**base, **bad})
        assert r.status_code == 422, bad
    for bad in (
        {"location_id": str(ctx["b"].id)},  # пост нельзя переносить
        {"name": None},
        {"post_type": None},
        {"id": str(uuid.uuid4())},
    ):
        r = await api.patch(f"{API}/posts/{p['id']}", headers=d, json=bad)
        assert r.status_code == 422, bad
    assert (await api.patch(f"{API}/posts/{p['id']}", headers=d, json={})).status_code == 200


# ---------------- запчасти ----------------


@integration
async def test_part_create_shape_and_defaults(api, db, ctx):
    d = ctx["d"]
    p = await mk_part(api, d, brand="Mann", barcode="4600000000011", sale_price="450.5")
    assert set(p) == {
        "id", "sku", "name", "brand", "barcode", "unit", "department", "sale_price", "is_active",
    }  # fmt: skip
    assert p["sale_price"] == "450.50" and p["brand"] == "Mann" and p["is_active"] is True
    q = await mk_part(api, d, sku="PLAIN", brand="", barcode="", sale_price=0)
    assert q["brand"] is None and q["barcode"] is None and q["sale_price"] == "0.00"
    assert (await api.get(f"{API}/parts", headers=ctx["m"])).json()["total"] == 2
    rows = await audit(db, "part", "create")
    assert {r.changes["sku"]["new"] for r in rows} == {"OF-100", "PLAIN"}
    assert any(r.changes["sale_price"]["new"] == "450.50" for r in rows)


@integration
async def test_part_duplicates_sku_and_barcode(api, ctx):
    d = ctx["d"]
    a = await mk_part(api, d, sku="S-1", barcode="111")
    r = await api.post(f"{API}/parts", headers=d, json=pbody(sku="S-1", barcode="222"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    r = await api.post(f"{API}/parts", headers=d, json=pbody(sku="S-2", barcode="111"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    assert "uq_" not in r.text and "parts" not in r.text
    # несколько запчастей без штрихкода допустимы
    await mk_part(api, d, sku="S-3")
    await mk_part(api, d, sku="S-4")
    b = await mk_part(api, d, sku="S-5", barcode="333")
    # смена штрихкода на занятый
    r = await api.patch(f"{API}/parts/{b['id']}", headers=d, json={"barcode": "111"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    # собственный штрихкод и сброс в null допустимы
    assert (
        await api.patch(f"{API}/parts/{b['id']}", headers=d, json={"barcode": "333"})
    ).status_code == 200
    r = await api.patch(f"{API}/parts/{b['id']}", headers=d, json={"barcode": None})
    assert r.status_code == 200 and r.json()["barcode"] is None
    # освободившийся штрихкод можно использовать
    assert (await api.patch(f"{API}/parts/{a['id']}", headers=d, json={"barcode": ""})).json()[
        "barcode"
    ] is None
    assert (
        await api.patch(f"{API}/parts/{b['id']}", headers=d, json={"barcode": "111"})
    ).status_code == 200


@integration
@pytest.mark.parametrize(
    "bad",
    [
        {"sku": ""},
        {"sku": "A B"},
        {"sku": "A" * 51},
        {"name": ""},
        {"name": "A" * 201},
        {"brand": "A" * 101},
        {"barcode": "A" * 51},
        {"barcode": "1 2"},
        {"unit": "box"},
        {"department": "none"},
        {"sale_price": "-1"},
        {"sale_price": "1.999"},
        {"sale_price": "NaN"},
        {"sale_price": "x"},
        {"is_active": False},
        {"id": str(uuid.uuid4())},
    ],
)
async def test_part_create_validation(api, ctx, bad):
    r = await api.post(f"{API}/parts", headers=ctx["d"], json=pbody(**bad))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


@integration
async def test_part_patch_and_audit(api, db, ctx):
    d = ctx["d"]
    p = await mk_part(api, d, brand="Mann")
    r = await api.patch(
        f"{API}/parts/{p['id']}",
        headers=d,
        json={"name": "Фильтр масляный", "brand": None, "unit": "set", "department": "both",
              "sale_price": "500", "is_active": False},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["name"] == "Фильтр масляный" and u["brand"] is None and u["unit"] == "set"
    assert u["department"] == "both" and u["sale_price"] == "500.00" and u["is_active"] is False
    assert u["sku"] == "OF-100"
    rows = await audit(db, "part", "update")
    assert rows[-1].changes["sale_price"] == {"old": "450.00", "new": "500.00"}
    for bad in ({"sku": "NEW"}, {"name": None}, {"sale_price": None}, {"id": str(uuid.uuid4())},
                {"unit": "box"}):  # fmt: skip
        assert (await api.patch(f"{API}/parts/{p['id']}", headers=d, json=bad)).status_code == 422
    assert (
        await api.patch(f"{API}/parts/{uuid.uuid4()}", headers=d, json={"name": "x"})
    ).status_code == 404
    assert (await api.delete(f"{API}/parts/{p['id']}", headers=d)).status_code == 405


@integration
async def test_part_list_filters_search_pagination(api, ctx):
    d, m = ctx["d"], ctx["m"]
    await mk_part(api, d, sku="OF-1", name="Фильтр масляный", brand="Mann", barcode="4600001")
    await mk_part(api, d, sku="AF-1", name="Фильтр воздушный", brand="Bosch", department="both")
    await mk_part(
        api, d, sku="WAX_1", name="Воск 100% карнаубский", unit="g", department="detailing"
    )
    off = await mk_part(api, d, sku="OLD-1", name="Старая деталь")
    await api.patch(f"{API}/parts/{off['id']}", headers=d, json={"is_active": False})

    async def skus(**params):
        r = await api.get(f"{API}/parts", headers=m, params=params)
        assert r.status_code == 200, (params, r.text)
        return [i["sku"] for i in r.json()["items"]]

    assert len(await skus()) == 4
    assert set(await skus(is_active="true")) == {"OF-1", "AF-1", "WAX_1"}
    # сортировка по названию
    names = [i["name"] for i in (await api.get(f"{API}/parts", headers=m)).json()["items"]]
    assert names == sorted(names)
    assert set(await skus(search="ФИЛЬТР")) == {"OF-1", "AF-1"}
    assert await skus(search="mann") == ["OF-1"]  # бренд
    assert await skus(search="4600001") == ["OF-1"]  # штрихкод
    assert await skus(search="af-") == ["AF-1"]  # артикул
    assert await skus(department="detailing") == ["WAX_1"]
    assert await skus(department="both") == ["AF-1"]
    assert set(await skus(is_active="false")) == {"OLD-1"}
    assert set(await skus(search="фильтр", department="service")) == {"OF-1"}
    # спецсимволы
    assert await skus(search="100%") == ["WAX_1"]
    assert await skus(search="X_1") == ["WAX_1"]
    assert await skus(search="X%1") == []
    assert await skus(search="'") == []
    assert await skus(search="Воск\x00") == ["WAX_1"]
    assert await skus(search="' OR 1=1 --") == []
    assert len(await skus(search="\x00")) == 4

    page = (await api.get(f"{API}/parts", headers=m, params={"limit": 3})).json()
    page2 = (await api.get(f"{API}/parts", headers=m, params={"limit": 3, "offset": 3})).json()
    assert (
        page["total"] == page2["total"] == 4
        and len(page["items"]) == 3
        and len(page2["items"]) == 1
    )
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"search": "A" * 101},
                   {"department": "x"}, {"is_active": "maybe"}):  # fmt: skip
        assert (await api.get(f"{API}/parts", headers=m, params=params)).status_code == 422


# ---------------- инъекции в текстовые поля ----------------


def _neutral(value):
    if isinstance(value, str):
        assert "\x00" not in value and "<" not in value and ">" not in value, value


@integration
@pytest.mark.parametrize("payload", ALL)
async def test_text_fields_injection(api, ctx, payload):
    d = ctx["d"]
    cat = await mk_cat(api, d, "Для инъекций")
    resp = []
    # категории, посты
    resp.append(
        await api.post(
            f"{API}/service-categories", headers=d, json={"name": payload, "department": "service"}
        )
    )
    resp.append(
        await api.post(
            f"{API}/locations/{ctx['a'].id}/posts",
            headers=d,
            json={"name": payload, "post_type": "lift", "department": "service"},
        )
    )
    # услуги
    for field in ("code", "name", "description"):
        body = sbody(cat["id"], **{"code": f"C-{uuid.uuid4().hex[:8]}", field: payload})
        resp.append(await api.post(f"{API}/services", headers=d, json=body))
    # запчасти
    for field in ("sku", "name", "brand", "barcode"):
        body = pbody(**{"sku": f"K-{uuid.uuid4().hex[:8]}", field: payload})
        resp.append(await api.post(f"{API}/parts", headers=d, json=body))
    for r in resp:
        assert r.status_code in (201, 422), (r.status_code, r.text[:200])
        if r.status_code == 201:
            for v in r.json().values():
                _neutral(v)
        else:
            assert payload not in r.text or len(payload) < 3
    # всё ещё читается
    for url in ("/service-categories", "/services?location_id=" + str(ctx["a"].id), "/parts"):
        assert (await api.get(f"{API}{url}", headers=d)).status_code == 200


@integration
@pytest.mark.parametrize("payload", MARKUP)
async def test_markup_is_rejected_not_stored(api, ctx, payload):
    d = ctx["d"]
    cat = await mk_cat(api, d)
    s = await mk_service(api, d, cat["id"])
    part = await mk_part(api, d)
    post = await mk_post(api, d, ctx["a"])
    attempts = [
        ("POST", "/service-categories", {"name": payload, "department": "service"}),
        ("PATCH", f"/service-categories/{cat['id']}", {"name": payload}),
        ("POST", "/services", sbody(cat["id"], code="XSS-1", name=payload)),
        ("POST", "/services", sbody(cat["id"], code="XSS-2", description=payload)),
        ("PATCH", f"/services/{s['id']}", {"name": payload}),
        ("PATCH", f"/services/{s['id']}", {"description": payload}),
        ("POST", f"/locations/{ctx['a'].id}/posts",
         {"name": payload, "post_type": "lift", "department": "service"}),
        ("PATCH", f"/posts/{post['id']}", {"name": payload}),
        ("POST", "/parts", pbody(sku="XSS-3", name=payload)),
        ("POST", "/parts", pbody(sku="XSS-4", brand=payload)),
        ("PATCH", f"/parts/{part['id']}", {"name": payload}),
        ("PATCH", f"/parts/{part['id']}", {"brand": payload}),
    ]  # fmt: skip
    for method, url, body in attempts:
        r = await api.request(method, f"{API}{url}", headers=ctx["d"], json=body)
        assert r.status_code == 422, (method, url, r.text)
        assert payload not in r.text
    # ничего не сохранилось
    assert (await api.get(f"{API}/services/{s['id']}", headers=d)).json()["name"] == "Замена масла"
    assert [c["name"] for c in (await api.get(f"{API}/service-categories", headers=d)).json()] == [
        "ТО"
    ]
    assert (await api.get(f"{API}/parts", headers=d)).json()["total"] == 1


@integration
async def test_nul_and_control_chars_are_stripped(api, ctx):
    d = ctx["d"]
    cat = await mk_cat(api, d, "Ка\x00те\x1bгория")
    assert cat["name"] == "Категория"
    s = await mk_service(api, d, cat["id"], name="Зам\x00ена", description="\x00")
    assert s["name"] == "Замена" and s["description"] is None
    p = await mk_part(api, d, brand="\x00")
    assert p["brand"] is None


@integration
async def test_unknown_fields_are_422_everywhere(api, ctx):
    d = ctx["d"]
    cat = await mk_cat(api, d)
    s = await mk_service(api, d, cat["id"])
    part = await mk_part(api, d)
    post = await mk_post(api, d, ctx["a"])
    for method, url, body in [
        ("POST", "/service-categories", {"name": "N", "department": "service", "x": 1}),
        ("PATCH", f"/service-categories/{cat['id']}", {"x": 1}),
        ("POST", "/services", sbody(cat["id"], code="U1", x=1)),
        ("PATCH", f"/services/{s['id']}", {"x": 1}),
        ("PUT", f"/services/{s['id']}/prices/{ctx['a'].id}", {"price": "1", "x": 1}),
        ("POST", f"/locations/{ctx['a'].id}/posts",
         {"name": "N", "post_type": "lift", "department": "service", "x": 1}),
        ("PATCH", f"/posts/{post['id']}", {"x": 1}),
        ("POST", "/parts", pbody(sku="U2", x=1)),
        ("PATCH", f"/parts/{part['id']}", {"x": 1}),
    ]:  # fmt: skip
        r = await api.request(method, f"{API}{url}", headers=d, json=body)
        assert r.status_code == 422, (method, url)
        assert r.json()["error"]["fields"] == {"x": "extra_forbidden"}
