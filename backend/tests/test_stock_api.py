"""Модуль 8: склад — приход, списание, перемещение, инвентаризация, сторно, интеграция с заказами."""

# ruff: noqa: E501

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import AuditLog, Client, Part, Role, User, Vehicle
from app.models.stock import StockBalance, StockMovement
from app.services import events
from app.services import stock_service as ss
from tests.factories import bearer, make_location, make_user

STOCK = "/api/v1/stock"

pytestmark = pytest.mark.integration


def token(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


async def seed(db: AsyncSession) -> SimpleNamespace:
    sfx = uuid.uuid4().hex[:8]
    a = await make_location(db, f"Склад А {sfx}")
    b = await make_location(db, f"Склад Б {sfx}")
    manager = await make_user(db, Role.manager, locations=[a])
    manager_b = await make_user(db, Role.manager, locations=[b])
    director = await make_user(db, Role.director)
    mechanic = await make_user(db, Role.mechanic, locations=[a])

    def part(name: str, **kw: object) -> Part:
        return Part(
            sku=f"SKU{uuid.uuid4().hex[:10]}",
            name=name,
            unit="pcs",
            department="both",
            sale_price=Decimal("500.00"),
            **kw,
        )

    p1 = part("Масляный фильтр", brand="Mann", barcode=f"46{uuid.uuid4().int % 10**11:011d}")
    p2 = part("Тормозные колодки")
    p3 = part("Снятая с производства", is_active=False)
    db.add_all([p1, p2, p3])
    await db.commit()
    return SimpleNamespace(
        a=a, b=b, p1=p1, p2=p2, p3=p3, manager=manager, director=director, mechanic=mechanic,
        m=token(manager), mb=token(manager_b), d=token(director), x=token(mechanic),
    )  # fmt: skip


@pytest.fixture
async def s(db: AsyncSession) -> SimpleNamespace:
    return await seed(db)


def receipt_body(loc: uuid.UUID, *lines: tuple[uuid.UUID, str, str], **kw: object) -> dict:
    return {
        "location_id": str(loc),
        "items": [{"part_id": str(p), "quantity": q, "unit_cost": c} for p, q, c in lines],
        **kw,
    }


async def receive(api: httpx.AsyncClient, s: SimpleNamespace, part: Part, q: str, cost: str, loc=None) -> dict:
    r = await api.post(
        f"{STOCK}/receipts",
        json=receipt_body(loc or s.a.id, (part.id, q, cost)),
        headers=s.m if loc is None else s.d,
    )
    assert r.status_code == 201, r.text
    return r.json()["movements"][0]


async def balance(api: httpx.AsyncClient, s: SimpleNamespace, part: Part, loc=None) -> dict:
    r = await api.get(f"{STOCK}/{part.id}", params={"location_id": str(loc or s.a.id)}, headers=s.d)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------- приход ----------------


async def test_receipt_weighted_average_and_audit(api, db, s):
    m1 = await receive(api, s, s.p1, "10.000", "100.00")
    assert m1["movement_type"] == "receipt" and m1["quantity"] == "10.000"
    assert m1["total"] == "1000.00" and m1["balance_after"] == "10.000" and m1["reversed"] is False
    m2 = await receive(api, s, s.p1, "10.000", "200.00")
    assert m2["balance_after"] == "20.000"
    b = await balance(api, s, s.p1)
    assert (b["quantity"], b["avg_cost"], b["stock_value"], b["is_low"]) == (
        "20.000", "150.00", "3000.00", False,
    )  # fmt: skip
    audits = (await db.scalars(select(AuditLog).where(AuditLog.entity_type == "stock_receipt"))).all()
    assert len(audits) >= 2 and audits[0].action == "create"
    assert not (await db.scalars(select(AuditLog).where(AuditLog.entity_id == uuid.UUID(m1["id"]), AuditLog.entity_type == "stock_movement"))).all()


async def test_receipt_validation_and_permissions(api, s):
    url = f"{STOCK}/receipts"
    line = (s.p1.id, "1.000", "10.00")
    ok = receipt_body(s.a.id, line)
    assert (await api.post(url, json=ok, headers=s.x)).status_code == 403
    assert (await api.post(url, json=ok, headers=s.mb)).status_code == 404  # чужая точка
    r = await api.post(url, json=receipt_body(s.a.id, line, line), headers=s.m)
    assert r.status_code == 422 and r.json()["error"]["fields"]["items"] == "duplicate_part"
    r = await api.post(url, json=receipt_body(s.a.id, (s.p3.id, "1.000", "1.00")), headers=s.m)
    assert r.status_code == 422 and "items" in r.json()["error"]["fields"]  # неактивная
    r = await api.post(url, json=receipt_body(s.a.id, (uuid.uuid4(), "1.000", "1.00")), headers=s.m)
    assert r.status_code == 422
    for bad in ("1.0005", "0.000", "-1.000", "1e3"):
        r = await api.post(url, json=receipt_body(s.a.id, (s.p1.id, bad, "1.00")), headers=s.m)
        assert r.status_code == 422, bad
    body = receipt_body(s.a.id, line)
    body["items"][0]["quantity"] = 1  # число JSON вместо строки
    assert (await api.post(url, json=body, headers=s.m)).status_code == 422
    assert (await api.post(url, json={**ok, "items": []}, headers=s.m)).status_code == 422
    assert (await api.post(url, json={**ok, "lol": 1}, headers=s.m)).status_code == 422


# ---------------- списание и событие stock.low ----------------


async def test_write_off_insufficient_and_low_event(api, db, s, monkeypatch):
    await receive(api, s, s.p1, "10.000", "100.00")
    assert (await api.patch(f"{STOCK}/{s.p1.id}", params={"location_id": str(s.a.id)}, json={"min_quantity": "5.000"}, headers=s.m)).status_code == 200
    seen: list[tuple[str, dict]] = []

    async def fake_publish(session, event_type, payload, **kw):
        seen.append((event_type, payload))

    monkeypatch.setattr(events, "publish", fake_publish)

    url = f"{STOCK}/write-offs"
    body = {"location_id": str(s.a.id), "reason": "Брак", "items": [{"part_id": str(s.p1.id), "quantity": "6.000"}]}
    r = await api.post(url, json=body, headers=s.m)
    assert r.status_code == 201, r.text
    mv = r.json()["movements"][0]
    assert mv["quantity"] == "-6.000" and mv["unit_cost"] == "100.00" and mv["total"] == "-600.00"
    assert mv["balance_after"] == "4.000" and mv["reason"] == "Брак"
    assert [e for e, _ in seen] == ["stock.low"]  # 10 -> 4 пересекло минимум 5
    assert seen[0][1]["quantity"] == "4.000" and seen[0][1]["min_quantity"] == "5.000"
    # повторное списание ниже порога событие не создаёт
    body["items"][0]["quantity"] = "1.000"
    assert (await api.post(url, json=body, headers=s.m)).status_code == 201
    assert len(seen) == 1
    assert (await balance(api, s, s.p1))["is_low"] is True

    # нехватка: транзакция откатывается целиком, 409 с details
    body = {
        "location_id": str(s.a.id), "reason": "Утеря",
        "items": [{"part_id": str(s.p1.id), "quantity": "1.000"}, {"part_id": str(s.p2.id), "quantity": "1.000"}],
    }  # fmt: skip
    r = await api.post(url, json=body, headers=s.m)
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"
    assert r.json()["error"]["details"] == {"part_id": str(s.p2.id), "available": "0.000", "requested": "1.000"}
    assert (await balance(api, s, s.p1))["quantity"] == "3.000"
    # причина обязательна, механик — 403
    assert (await api.post(url, json={**body, "reason": "ab"}, headers=s.m)).status_code == 422
    assert (await api.post(url, json=body, headers=s.x)).status_code == 403


# ---------------- перемещение ----------------


async def test_transfer_director_only_and_costs(api, db, s):
    await receive(api, s, s.p1, "10.000", "100.00")
    await receive(api, s, s.p1, "5.000", "40.000"[:-1], loc=s.b.id)  # в точке Б: 5 по 40.00
    url = f"{STOCK}/transfers"
    body = {"from_location_id": str(s.a.id), "to_location_id": str(s.b.id), "comment": "Переброска",
            "items": [{"part_id": str(s.p1.id), "quantity": "4.000"}]}  # fmt: skip
    assert (await api.post(url, json=body, headers=s.m)).status_code == 403
    same = {**body, "to_location_id": str(s.a.id)}
    r = await api.post(url, json=same, headers=s.d)
    assert r.status_code == 422 and "to_location_id" in r.json()["error"]["fields"]
    r = await api.post(url, json=body, headers=s.d)
    assert r.status_code == 201, r.text
    out, inn = r.json()["out"][0], r.json()["in"][0]
    assert out["movement_type"] == "transfer_out" and out["quantity"] == "-4.000" and out["unit_cost"] == "100.00"
    assert inn["movement_type"] == "transfer_in" and inn["quantity"] == "4.000" and inn["unit_cost"] == "100.00"
    assert inn["related_movement_id"] == out["id"] and inn["reason"] == "Переброска"
    assert (await balance(api, s, s.p1))["quantity"] == "6.000"
    bb = await balance(api, s, s.p1, s.b.id)  # (5*40 + 4*100)/9 = 66.67
    assert (bb["quantity"], bb["avg_cost"]) == ("9.000", "66.67")
    big = {**body, "items": [{"part_id": str(s.p1.id), "quantity": "100.000"}]}
    r = await api.post(url, json=big, headers=s.d)
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"


# ---------------- инвентаризация ----------------


async def test_inventory_commit_stock_changed_and_adjustments(api, db, s):
    await receive(api, s, s.p1, "10.000", "100.00")
    url = f"{STOCK}/inventory/commit"

    def inv(*lines: tuple[Part, str, str]) -> dict:
        return {"location_id": str(s.a.id), "items": [
            {"part_id": str(p.id), "expected_quantity": e, "actual_quantity": a} for p, e, a in lines]}  # fmt: skip

    stale = inv((s.p1, "9.000", "8.000"))
    r = await api.post(url, json=stale, headers=s.m)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stock_changed"
    assert r.json()["error"]["details"] == {"part_id": str(s.p1.id)}
    assert (await api.post(url, json=inv((s.p1, "10.000", "-1.000")), headers=s.m)).status_code == 422
    r = await api.post(url, json=inv((s.p1, "10.000", "7.500"), (s.p2, "0.000", "0.000")), headers=s.m)
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["skipped"] == 1 and len(j["movements"]) == 1
    adj = j["movements"][0]
    assert adj["movement_type"] == "adjustment" and adj["quantity"] == "-2.500" and adj["reason"] == "Инвентаризация"
    assert adj["balance_after"] == "7.500" and adj["unit_cost"] == "100.00"
    b = await balance(api, s, s.p1)
    assert b["quantity"] == "7.500" and b["avg_cost"] == "100.00"
    # положительная корректировка по нулевому остатку: себестоимость 0.00
    r = await api.post(url, json=inv((s.p2, "0.000", "3.000")), headers=s.m)
    assert r.json()["movements"][0]["unit_cost"] == "0.00"


# ---------------- сторно ----------------


async def test_reverse_rules(api, db, s):
    m = await receive(api, s, s.p1, "5.000", "80.00")
    url = f"{STOCK}/movements/{m['id']}/reverse"
    assert (await api.post(url, json={"reason": "Ошибка"}, headers=s.x)).status_code == 403
    assert (await api.post(url, json={"reason": "Ошибка"}, headers=s.mb)).status_code == 404
    assert (await api.post(url, json={"reason": "no"}, headers=s.m)).status_code == 422
    r = await api.post(url, json={"reason": "Ошибка ввода"}, headers=s.m)
    assert r.status_code == 201, r.text
    rev = r.json()
    assert rev["movement_type"] == "adjustment" and rev["quantity"] == "-5.000"
    assert rev["related_movement_id"] == m["id"] and rev["unit_cost"] == "80.00"
    assert (await balance(api, s, s.p1))["quantity"] == "0.000"
    r = await api.post(url, json={"reason": "Ещё раз"}, headers=s.m)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_reversed"
    lst = await api.get(f"{STOCK}/movements", params={"location_id": str(s.a.id), "part_id": str(s.p1.id)}, headers=s.m)
    flags = {i["id"]: i["reversed"] for i in lst.json()["items"]}
    assert flags[m["id"]] is True and flags[rev["id"]] is False

    # сторно прихода, когда товар уже ушёл → 409 insufficient_stock
    m2 = await receive(api, s, s.p2, "2.000", "10.00")
    wo = {"location_id": str(s.a.id), "reason": "Потеря", "items": [{"part_id": str(s.p2.id), "quantity": "2.000"}]}
    wr = await api.post(f"{STOCK}/write-offs", json=wo, headers=s.m)
    r = await api.post(f"{STOCK}/movements/{m2['id']}/reverse", json={"reason": "Ошибка"}, headers=s.m)
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_stock"
    # сторно списания возвращает остаток
    r = await api.post(f"{STOCK}/movements/{wr.json()['movements'][0]['id']}/reverse", json={"reason": "Нашли"}, headers=s.m)
    assert r.status_code == 201 and r.json()["quantity"] == "2.000"

    # менеджер: движение старше 7 суток → 403, директор — можно
    old = StockMovement(
        location_id=s.a.id, part_id=s.p2.id, movement_type="receipt", quantity=Decimal("1.000"),
        unit_cost=Decimal("10.00"), balance_after=Decimal("3.000"), created_by=s.manager.id,
        created_at=datetime.now(UTC) - timedelta(days=8),
    )  # fmt: skip
    db.add(old)
    await db.commit()
    url = f"{STOCK}/movements/{old.id}/reverse"
    assert (await api.post(url, json={"reason": "Давно"}, headers=s.m)).status_code == 403
    assert (await api.post(url, json={"reason": "Давно"}, headers=s.d)).status_code == 201


# ---------------- заказы: выдача, возврат, остатки ----------------


async def make_order(db: AsyncSession, s: SimpleNamespace) -> SimpleNamespace:
    client = Client(client_type="person", full_name="Клиент", phone="+79" + str(uuid.uuid4().int)[:9])
    db.add(client)
    await db.flush()
    car = Vehicle(client_id=client.id, make="Kia", model="Rio")
    db.add(car)
    await db.flush()
    oid = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO work_orders (id, number, location_id, client_id, vehicle_id, department, manager_id) "
            "VALUES (:id, :n, :l, :c, :v, 'service', :m)"
        ),
        {"id": oid, "n": f"T-{uuid.uuid4().hex[:8]}", "l": s.a.id, "c": client.id, "v": car.id, "m": s.manager.id},
    )
    await db.commit()
    return SimpleNamespace(id=oid, location_id=s.a.id)


async def test_order_issue_return_and_stock_for_parts(api, db, s):
    await receive(api, s, s.p1, "5.000", "100.00")
    await receive(api, s, s.p1, "5.000", "200.00")  # avg 150
    order = await make_order(db, s)
    uid = s.manager.id

    assert await ss.issue_for_order(db, order=order, part_id=None, quantity=Decimal(1), actor_id=uid) is None
    res = await ss.issue_for_order(db, order=order, part_id=s.p1.id, quantity=Decimal("3.000"), actor_id=uid)
    assert res is not None and res.unit_cost == Decimal("150.00")
    mv = await db.get(StockMovement, res.movement_id)
    assert (mv.movement_type, mv.quantity, mv.work_order_id, mv.balance_after) == (
        "issue_to_order", Decimal("-3.000"), order.id, Decimal("7.000"),
    )  # fmt: skip
    assert await ss.stock_for_parts(db, location_id=s.a.id, part_ids=[s.p1.id, s.p2.id]) == {
        s.p1.id: Decimal("7.000"), s.p2.id: Decimal("0.000"),
    }  # fmt: skip

    with pytest.raises(AppError) as ei:
        await ss.issue_for_order(db, order=order, part_id=s.p1.id, quantity=Decimal("8.000"), actor_id=uid)
    assert ei.value.status == 409 and ei.value.code == "insufficient_stock"
    assert ei.value.details == {"part_id": str(s.p1.id), "available": "7.000", "requested": "8.000"}

    row = SimpleNamespace(stock_movement_id=res.movement_id, quantity=Decimal("3.000"))
    await ss.return_for_order(db, order=order, part_row=row, actor_id=uid)
    await ss.return_for_order(db, order=order, part_row=row, actor_id=uid)  # идемпотентно
    await ss.return_for_order(db, order=order, part_row=SimpleNamespace(stock_movement_id=None, quantity=Decimal(1)), actor_id=uid)
    bal = await db.get(StockBalance, (s.a.id, s.p1.id), populate_existing=True)
    assert bal.quantity == Decimal("10.000")
    rets = (await db.scalars(select(StockMovement).where(StockMovement.movement_type == "return_from_order"))).all()
    assert len(rets) == 1 and rets[0].related_movement_id == res.movement_id and rets[0].unit_cost == Decimal("150.00")

    # движения заказа видны в ленте с номером заказа; выдачу через API сторнировать нельзя
    r = await api.get(f"{STOCK}/movements", params={"location_id": str(s.a.id), "work_order_id": str(order.id)}, headers=s.m)
    items = r.json()["items"]
    assert {i["movement_type"] for i in items} == {"issue_to_order", "return_from_order"}
    assert items[0]["work_order"]["id"] == str(order.id) and items[0]["work_order"]["number"]
    r = await api.post(f"{STOCK}/movements/{res.movement_id}/reverse", json={"reason": "Хочу"}, headers=s.m)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"


# ---------------- остатки: список, поиск, права ----------------


async def test_list_stock_scopes_search_totals(api, db, s):
    await receive(api, s, s.p1, "10.000", "100.00")
    await receive(api, s, s.p2, "2.000", "50.00")
    await api.patch(f"{STOCK}/{s.p2.id}", params={"location_id": str(s.a.id)}, json={"min_quantity": "5"}, headers=s.m)
    q = {"location_id": str(s.a.id)}
    r = await api.get(STOCK, params=q, headers=s.m)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 2 and j["totals"] == {"positions": 2, "low_count": 1, "stock_value": "1100.00"}
    names = [i["part"]["name"] for i in j["items"]]
    assert names == sorted(names)
    assert {i["part"]["name"]: i["is_low"] for i in j["items"]} == {"Масляный фильтр": False, "Тормозные колодки": True}
    r = await api.get(STOCK, params={**q, "scope": "low"}, headers=s.m)
    assert [i["part"]["id"] for i in r.json()["items"]] == [str(s.p2.id)]
    r = await api.get(STOCK, params={**q, "scope": "all"}, headers=s.m)
    assert r.json()["total"] >= 2 and s.p3.id not in {uuid.UUID(i["part"]["id"]) for i in r.json()["items"]}
    r = await api.get(STOCK, params={**q, "search": s.p1.barcode}, headers=s.m)
    assert [i["part"]["id"] for i in r.json()["items"]] == [str(s.p1.id)]
    r = await api.get(STOCK, params={**q, "sort": "stock_value", "order": "desc"}, headers=s.m)
    assert r.json()["items"][0]["part"]["id"] == str(s.p1.id)
    assert (await api.get(STOCK, params={**q, "sort": "bogus"}, headers=s.m)).status_code == 422
    assert (await api.get(STOCK, params={**q, "scope": "bogus"}, headers=s.m)).status_code == 422
    # location_id обязателен; чужая точка — 404; механик — 403 везде
    r = await api.get(STOCK, headers=s.m)
    assert r.status_code == 422 and "location_id" in r.json()["error"]["fields"]
    assert (await api.get(STOCK, params=q, headers=s.mb)).status_code == 404
    assert (await api.get(STOCK, params=q, headers=s.x)).status_code == 403
    assert (await api.get(f"{STOCK}/movements", params=q, headers=s.x)).status_code == 403
    assert (await api.patch(f"{STOCK}/{s.p1.id}", params=q, json={"min_quantity": "1"}, headers=s.x)).status_code == 403
    # позиция без остатка: нули и updated_at = null
    b = await balance(api, s, s.p3)
    assert (b["quantity"], b["avg_cost"], b["updated_at"]) == ("0.000", "0.00", None)
    assert (await api.get(f"{STOCK}/{uuid.uuid4()}", params=q, headers=s.m)).status_code == 404


async def test_movements_period_and_immutability(api, db, s):
    await receive(api, s, s.p1, "1.000", "10.00")
    q = {"location_id": str(s.a.id)}
    r = await api.get(f"{STOCK}/movements", params={**q, "date_from": "2020-01-01", "date_to": "2021-06-01"}, headers=s.m)
    assert r.status_code == 422 and "date_to" in r.json()["error"]["fields"]
    today = datetime.now(UTC).date()
    r = await api.get(f"{STOCK}/movements", params={**q, "date_from": str(today - timedelta(days=1)), "date_to": str(today + timedelta(days=1)), "movement_type": "receipt"}, headers=s.m)
    assert r.status_code == 200 and r.json()["total"] == 1
    # движения неизменяемы даже для владельца таблицы
    with pytest.raises(DBAPIError):
        await db.execute(text("UPDATE stock_movements SET reason = 'x'"))
    await db.rollback()
    cnt = await db.scalar(select(func.count()).select_from(StockMovement))
    assert cnt is not None
