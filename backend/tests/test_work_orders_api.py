"""Модуль 5: заказ-наряды — создание, суммы, статусы, версии, права, создание из записи, PDF."""

# ruff: noqa: E501

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func

from app.core.security import create_access_token
from app.models import Client, Role, Service, ServiceCategory, User, Vehicle
from tests.factories import bearer, make_location, make_user

API = "/api/v1"
WO = f"{API}/work-orders"

pytestmark = pytest.mark.integration


def token(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


@pytest.fixture
async def ctx(api, db):
    sfx = uuid.uuid4().hex[:8]
    a = await make_location(db, f"Точка А {sfx}")
    b = await make_location(db, f"Точка Б {sfx}")
    manager = await make_user(db, Role.manager, locations=[a])
    manager_b = await make_user(db, Role.manager, locations=[b])
    director = await make_user(db, Role.director)
    mechanic = await make_user(db, Role.mechanic, locations=[a])
    client = Client(client_type="person", full_name="Иван Петров", phone="+79" + str(uuid.uuid4().int)[:9])
    db.add(client)
    await db.flush()
    vehicle = Vehicle(client_id=client.id, make="Kia", model="Rio", plate_number="А123ВС77", mileage=1000)
    cat = ServiceCategory(name=f"ТО {sfx}", department="service")
    db.add_all([vehicle, cat])
    await db.flush()
    svc = Service(
        category_id=cat.id, code="S" + uuid.uuid4().hex[:12], name="Замена масла", department="service",
        unit="pcs", base_price=Decimal("1500.00"), norm_hours=Decimal("0.50"), duration_minutes=30,
    )  # fmt: skip
    db.add(svc)
    await db.commit()
    return SimpleNamespace(
        a=a, b=b, client=client, vehicle=vehicle, svc=svc, mechanic=mechanic,
        m=token(manager), mb=token(manager_b), d=token(director), x=token(mechanic),
    )  # fmt: skip


def payload(c, **kw):
    return {"location_id": str(c.a.id), "client_id": str(c.client.id), "vehicle_id": str(c.vehicle.id), **kw}


async def make(api, c, h=None, **kw):
    r = await api.post(WO, headers=h or c.m, json=payload(c, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def custom(price="100.00", qty="1.00", **kw):
    return {"name": "Диагностика ходовой", "department": "service", "unit_price": price, "quantity": qty, **kw}


async def status(api, c, order, to, h=None, **kw):
    return await api.post(
        f"{WO}/{order['id']}/status", headers=h or c.m, json={"version": order["version"], "status": to, **kw}
    )


def code(r):
    return r.json()["error"]["code"]


async def test_create_empty_order_and_number(api, ctx):
    o = await make(api, ctx)
    assert o["status"] == "new" and o["version"] == 1 and o["total"] == "0.00"
    assert o["number"].startswith(ctx.a.code + "-") and len(o["number"].split("-")[1]) == 6
    o2 = await make(api, ctx)
    assert int(o2["number"].split("-")[1]) == int(o["number"].split("-")[1]) + 1
    assert o["allowed_transitions"] == ["diagnostics", "in_progress", "cancelled"]


async def test_totals_with_catalog_custom_items_parts_and_discount(api, ctx):
    o = await make(
        api, ctx, discount_percent="10.00",
        items=[{"service_id": str(ctx.svc.id), "quantity": "2.00", "discount_percent": "10.00"}, custom("100.00", "1.00")],
    )  # fmt: skip
    # 2 * 1500 - 10% = 2700; + 100 = 2800 работ
    assert o["works_total"] == "2800.00" and o["parts_total"] == "0.00"
    assert o["total"] == "2520.00" and o["discount_total"] == "280.00"
    cat_item = next(i for i in o["items"] if i["service_id"])
    assert cat_item["unit_price"] == "1500.00" and cat_item["total"] == "2700.00" and cat_item["norm_hours"] == "0.50"
    r = await api.post(
        f"{WO}/{o['id']}/parts", headers=ctx.m,
        json={"version": o["version"], "name": "Фильтр", "quantity": "1.500", "unit_price": "40.00"},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["version"] == o["version"] + 1 and p["parts_total"] == "60.00"
    assert p["total"] == "2574.00"  # (2800 + 60) * 0.9
    assert p["parts"][0]["unit_cost"] is None


async def test_money_must_be_strings_and_rounding(api, ctx):
    r = await api.post(WO, headers=ctx.m, json=payload(ctx, items=[{**custom(), "unit_price": 100}]))
    assert r.status_code == 422
    o = await make(api, ctx, items=[custom("33.33", "0.50")])
    assert o["items"][0]["total"] == "16.67"  # ROUND_HALF_UP


async def test_status_flow_and_guards(api, ctx):
    o = await make(api, ctx)
    r = await status(api, ctx, o, "in_progress")
    assert code(r) == "order_empty"
    r = await status(api, ctx, o, "ready")
    assert code(r) == "invalid_transition"
    r = await status(api, ctx, o, "cancelled")
    assert code(r) == "validation_error"  # cancel_reason обязателен
    r = await api.post(f"{WO}/{o['id']}/items", headers=ctx.m, json={"version": 1, **custom()})
    o = r.json()
    r = await status(api, ctx, o, "in_progress")
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "in_progress" and o["version"] == 3 and o["started_at"]
    r = await status(api, ctx, o, "quality_check")
    assert r.status_code == 200
    o = r.json()
    r = await status(api, ctx, o, "ready")  # работа не выполнена
    assert code(r) == "items_not_done"
    assert r.json()["error"]["details"] == {"pending_count": "1"}
    r = await status(api, ctx, o, "in_progress")
    o = r.json()
    item = o["items"][0]
    r = await api.post(f"{WO}/{o['id']}/items/{item['id']}/complete", headers=ctx.m, json={"version": o["version"]})
    assert code(r) == "validation_error"  # нужен механик
    r = await api.patch(
        f"{WO}/{o['id']}/items/{item['id']}", headers=ctx.m,
        json={"version": o["version"], "mechanic_id": str(ctx.mechanic.id)},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    o = r.json()
    r = await api.post(f"{WO}/{o['id']}/items/{item['id']}/complete", headers=ctx.m, json={"version": o["version"]})
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "quality_check"  # on_item_done: автопереход
    r = await api.get(f"{WO}/{o['id']}/history", headers=ctx.m)
    assert [h["to_status"] for h in r.json()][-1] == "quality_check"
    assert r.json()[-1]["comment"] == "Все работы выполнены"
    r = await status(api, ctx, o, "ready")
    assert r.status_code == 200, r.text
    r = await api.get(f"{WO}/{o['id']}/print/act", headers=ctx.m)  # акт доступен в ready
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert f"{o['number']}-act.pdf" in r.headers["content-disposition"]


async def test_cancel_requires_reason_and_final_state(api, ctx):
    o = await make(api, ctx, items=[custom()])
    r = await status(api, ctx, o, "cancelled", cancel_reason="Клиент отказался")
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["status"] == "cancelled" and o["items"][0]["status"] == "cancelled" and o["total"] == "0.00"
    r = await api.patch(f"{WO}/{o['id']}", headers=ctx.m, json={"version": o["version"], "complaint": "x"})
    assert code(r) == "invalid_state"


async def test_version_conflict(api, ctx):
    o = await make(api, ctx)
    r = await api.patch(f"{WO}/{o['id']}", headers=ctx.m, json={"version": 1, "complaint": "Стук"})
    assert r.status_code == 200 and r.json()["version"] == 2
    r = await api.patch(f"{WO}/{o['id']}", headers=ctx.m, json={"version": 1, "complaint": "Скрип"})
    assert r.status_code == 409 and code(r) == "version_conflict"
    assert r.json()["error"]["details"] == {"current_version": "2"}
    r = await api.delete(f"{WO}/{o['id']}/items/{uuid.uuid4()}?version=1", headers=ctx.m)
    assert code(r) == "version_conflict"


async def test_comment_does_not_bump_version(api, ctx):
    o = await make(api, ctx)
    r = await api.post(f"{WO}/{o['id']}/comments", headers=ctx.m, json={"text": "Позвонить клиенту"})
    assert r.status_code == 201 and r.json()["is_internal"] is True
    assert (await api.get(f"{WO}/{o['id']}", headers=ctx.m)).json()["version"] == 1


async def test_roles_and_location_isolation(api, ctx):
    o = await make(api, ctx)
    assert (await api.get(WO, headers=ctx.x)).status_code == 403
    assert (await api.get(f"{WO}/{o['id']}", headers=ctx.x)).status_code == 403
    assert (await api.get(f"{WO}/{o['id']}", headers=ctx.mb)).status_code == 404  # чужая точка
    r = await api.post(WO, headers=ctx.mb, json=payload(ctx))
    assert r.status_code == 404
    assert (await api.get(WO, headers=ctx.mb)).json()["total"] == 0
    assert (await api.get(WO, headers=ctx.d)).json()["total"] >= 1
    assert (await api.get(WO, headers=ctx.m)).status_code == 200


async def test_manager_cannot_change_catalog_price_director_can(api, ctx):
    r = await api.post(WO, headers=ctx.m, json=payload(ctx, items=[{"service_id": str(ctx.svc.id), "unit_price": "1.00"}]))
    assert r.status_code == 403
    r = await api.post(WO, headers=ctx.d, json=payload(ctx, items=[{"service_id": str(ctx.svc.id), "unit_price": "1.00"}]))
    assert r.status_code == 201, r.text
    assert r.json()["items"][0]["unit_price"] == "1.00"


async def test_create_from_appointment(api, ctx):
    ap = await api.post(
        f"{API}/appointments", headers=ctx.m,
        json={
            "location_id": str(ctx.a.id), "client_id": str(ctx.client.id), "vehicle_id": str(ctx.vehicle.id),
            "department": "service", "start_at": "2026-11-20T10:00:00+03:00", "end_at": "2026-11-20T11:00:00+03:00",
            "service_ids": [str(ctx.svc.id)],
        },
    )  # fmt: skip
    assert ap.status_code == 201, ap.text
    ap = ap.json()
    r = await api.post(WO, headers=ctx.m, json={"location_id": str(ctx.a.id), "appointment_id": ap["id"], "mileage_in": 5000})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["appointment_id"] == ap["id"] and o["client"]["id"] == str(ctx.client.id)
    assert [i["service_id"] for i in o["items"]] == [str(ctx.svc.id)] and o["total"] == "1500.00"
    got = (await api.get(f"{API}/appointments/{ap['id']}", headers=ctx.m)).json()
    assert got["status"] == "arrived" and got["work_order_id"] == o["id"] and got["work_order_number"] == o["number"]
    v = (await api.get(f"{API}/vehicles/{ctx.vehicle.id}", headers=ctx.m)).json()
    assert v["mileage"] == 5000
    r = await api.post(WO, headers=ctx.m, json={"location_id": str(ctx.a.id), "appointment_id": ap["id"]})
    assert r.status_code == 409 and code(r) == "appointment_has_order"


async def test_list_filters_history_and_mechanics(api, ctx):
    o = await make(api, ctx, items=[custom()])
    r = await api.get(f"{WO}?status=new,diagnostics&search={o['number']}", headers=ctx.m)
    assert [x["id"] for x in r.json()["items"]] == [o["id"]]
    assert (await api.get(f"{WO}?status=bogus", headers=ctx.m)).status_code == 422
    hist = await api.get(f"{API}/clients/{ctx.client.id}/work-orders", headers=ctx.m)
    assert hist.json()["total"] == 1
    assert (await api.get(f"{API}/vehicles/{ctx.vehicle.id}/work-orders", headers=ctx.mb)).json()["total"] == 0
    assert (await api.get(f"{API}/clients/{uuid.uuid4()}/work-orders", headers=ctx.m)).status_code == 404
    r = await api.get(f"{WO}/mechanics?location_id={ctx.a.id}", headers=ctx.m)
    assert [m["id"] for m in r.json()] == [str(ctx.mechanic.id)]
    assert (await api.get(f"{WO}/mechanics?location_id={ctx.a.id}", headers=ctx.mb)).status_code == 404
    assert (await api.get(f"{WO}/mechanics?location_id={ctx.a.id}", headers=ctx.x)).status_code == 403


async def test_board_summary_and_duplicate(api, ctx):
    o = await make(api, ctx, items=[custom()])
    b = (await api.get(f"{WO}/board?location_id={ctx.a.id}", headers=ctx.m)).json()
    col = next(c for c in b["columns"] if c["status"] == "new")
    assert col["total"] >= 1 and any(i["id"] == o["id"] for i in col["items"])
    s = (await api.get(f"{WO}/summary?location_id={ctx.a.id}", headers=ctx.m)).json()
    assert s["open_total"] >= 1
    r = await api.post(f"{WO}/{o['id']}/duplicate", headers=ctx.m, json={})
    assert r.status_code == 201 and r.json()["id"] != o["id"] and r.json()["status"] == "new"
    assert r.json()["items"][0]["status"] == "pending"


async def test_pdf_print_forms(api, ctx):
    o = await make(api, ctx, complaint="Стук & скрип (\"в\") подвеске", items=[custom("100.00", "1.00", name="Работа & масло")])
    r = await api.get(f"{WO}/{o['id']}/print/work-order", headers=ctx.m)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and r.content.rstrip().endswith(b"%%EOF")
    assert "inline" in r.headers["content-disposition"] and f"{o['number']}-order.pdf" in r.headers["content-disposition"]
    r = await api.get(f"{WO}/{o['id']}/print/act", headers=ctx.m)
    assert r.status_code == 409 and code(r) == "invalid_state"
    assert (await api.get(f"{WO}/{o['id']}/print/work-order", headers=ctx.mb)).status_code == 404
    assert func is not None
