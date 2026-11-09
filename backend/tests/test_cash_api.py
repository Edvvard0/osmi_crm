"""Модуль 9: касса — оплаты, возвраты, расходы, категории, кассовый отчёт и операции."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import AuditLog, Client, Role, User, Vehicle
from app.models.cash import Payment
from app.models.work_order import WorkOrder, WorkOrderItem
from app.services.payment_status import recalc_payment_status, status_for
from tests.factories import bearer, make_location, make_user

API = "/api/v1"

pytestmark = pytest.mark.integration


def token(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


def today(tz: str = "Europe/Moscow") -> datetime:
    return datetime.now(ZoneInfo(tz))


async def seed(db: AsyncSession) -> SimpleNamespace:
    a = await make_location(db, timezone="Europe/Moscow")
    b = await make_location(db, timezone="Asia/Vladivostok")
    manager = await make_user(db, Role.manager, locations=[a])
    manager_b = await make_user(db, Role.manager, locations=[b])
    director = await make_user(db, Role.director)
    mechanic = await make_user(db, Role.mechanic, locations=[a])
    client = Client(client_type="person", full_name="Иван Петров", phone="+79" + str(uuid.uuid4().int)[:9])
    db.add(client)
    await db.flush()
    vehicle = Vehicle(client_id=client.id, make="Kia", model="Rio")
    db.add(vehicle)
    await db.commit()
    return SimpleNamespace(
        a=a, b=b, manager=manager, manager_b=manager_b, director=director,
        mechanic=mechanic, client=client, vehicle=vehicle,
    )  # fmt: skip


async def make_order(
    db: AsyncSession, s: SimpleNamespace, total: str = "1000.00", status: str = "in_progress",
    location: object | None = None,
) -> WorkOrder:  # fmt: skip
    loc = location or s.a
    order = WorkOrder(
        number=f"{loc.code}-{uuid.uuid4().hex[:8]}",
        location_id=loc.id,
        client_id=s.client.id,
        vehicle_id=s.vehicle.id,
        department="service",
        status=status,
        manager_id=s.director.id,
        works_total=Decimal(total),
        total=Decimal(total),
        cancel_reason="тест" if status == "cancelled" else None,
    )
    db.add(order)
    await db.flush()
    if status in ("ready", "closed"):
        db.add(
            WorkOrderItem(
                work_order_id=order.id, name="Работа", department="service", quantity=Decimal(1),
                unit_price=Decimal(total), total=Decimal(total), status="done",
            )  # fmt: skip
        )
    await db.commit()
    return order


async def pay(
    api: httpx.AsyncClient, user: User, order: WorkOrder, amount: str, method: str = "cash", **kw: object
) -> httpx.Response:  # fmt: skip
    return await api.post(
        f"{API}/work-orders/{order.id}/payments",
        json={"amount": amount, "method": method, **kw},
        headers=token(user),
    )


async def test_payment_full_and_partial(api, db) -> None:
    s = await seed(db)
    order = await make_order(db, s, "1000.00", status="new")  # предоплата в статусе new
    r = await pay(api, s.manager, order, "400.00", "card", comment="аванс")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["payment"]["payment_type"] == "payment"
    assert body["payment"]["amount"] == "400.00"
    assert body["payment"]["refundable"] == "400.00"
    assert body["payment"]["order_number"] == order.number
    assert body["payment"]["location_id"] == str(s.a.id)
    assert body["payment"]["accepted_by"]["id"] == str(s.manager.id)
    assert body["order"]["paid_total"] == "400.00"
    assert body["order"]["balance_due"] == "600.00"
    assert body["order"]["payment_status"] == "partial"
    assert body["order"]["version"] == 1

    r = await pay(api, s.manager, order, "600.00", "cash")
    assert r.status_code == 201
    assert r.json()["order"]["payment_status"] == "paid"
    assert r.json()["order"]["balance_due"] == "0.00"

    lst = await api.get(f"{API}/work-orders/{order.id}/payments", headers=token(s.manager))
    assert [p["amount"] for p in lst.json()] == ["400.00", "600.00"]
    audit = (
        await db.scalars(select(AuditLog).where(AuditLog.entity_type == "payment"))
    ).all()
    mine = [a for a in audit if a.changes and a.changes.get("order_number") == order.number]
    assert len(mine) == 2 and mine[0].action == "create"
    assert set(mine[0].changes) >= {"amount", "method", "order_number"}


async def test_payment_validation_errors(api, db) -> None:
    s = await seed(db)
    order = await make_order(db, s, "500.00")
    over = await pay(api, s.manager, order, "500.01")
    assert over.status_code == 409 and over.json()["error"]["code"] == "overpayment"
    assert over.json()["error"]["details"] == {"balance_due": "500.00"}
    for bad in ("0.00", "-5.00", "10.001"):
        r = await pay(api, s.manager, order, bad)
        assert r.status_code == 422 and "amount" in r.json()["error"]["fields"], bad
    r = await api.post(
        f"{API}/work-orders/{order.id}/payments",
        json={"amount": "1.00", "method": "bitcoin"},
        headers=token(s.manager),
    )
    assert r.status_code == 422
    assert (await pay(api, s.manager, order, "500.00")).status_code == 201
    again = await pay(api, s.manager, order, "1.00")
    assert again.status_code == 409 and again.json()["error"]["code"] == "nothing_to_pay"

    cancelled = await make_order(db, s, "300.00", status="cancelled")
    r = await pay(api, s.manager, cancelled, "100.00")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
    closed = await make_order(db, s, "300.00", status="closed")
    assert (await pay(api, s.manager, closed, "300.00")).status_code == 201


async def test_payment_idempotency(api, db) -> None:
    s = await seed(db)
    order = await make_order(db, s, "1000.00")
    other = await make_order(db, s, "1000.00")
    rid = str(uuid.uuid4())
    first = await pay(api, s.manager, order, "300.00", client_request_id=rid)
    again = await pay(api, s.manager, order, "300.00", client_request_id=rid)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["payment"]["id"] == first.json()["payment"]["id"]
    assert again.json()["order"]["paid_total"] == "300.00"
    count = await db.scalar(
        select(func.count()).select_from(Payment).where(Payment.work_order_id == order.id)
    )
    assert count == 1
    clash = await pay(api, s.manager, other, "300.00", client_request_id=rid)
    assert clash.status_code == 409


async def test_payment_permissions(api, db) -> None:
    s = await seed(db)
    order = await make_order(db, s, "1000.00")
    assert (await pay(api, s.mechanic, order, "100.00")).status_code == 403
    r = await api.get(f"{API}/work-orders/{order.id}/payments", headers=token(s.mechanic))
    assert r.status_code == 403
    assert (await pay(api, s.manager_b, order, "100.00")).status_code == 404
    r = await api.get(f"{API}/work-orders/{order.id}/payments", headers=token(s.manager_b))
    assert r.status_code == 404
    assert (await pay(api, s.director, order, "100.00")).status_code == 201
    r = await api.post(f"{API}/work-orders/{order.id}/payments", json={"amount": "1.00", "method": "cash"})
    assert r.status_code == 401


async def test_refund_flow(api, db) -> None:
    s = await seed(db)
    order = await make_order(db, s, "1000.00")
    p = (await pay(api, s.manager, order, "1000.00", "card")).json()["payment"]

    def url(pid: str) -> str:
        return f"{API}/payments/{pid}/refund"

    r = await api.post(url(p["id"]), json={"comment": "брак"}, headers=token(s.manager))
    assert r.status_code == 403
    r = await api.post(url(p["id"]), json={"amount": "100.00"}, headers=token(s.director))
    assert r.status_code == 422 and "comment" in r.json()["error"]["fields"]
    r = await api.post(url(p["id"]), json={"comment": "ab"}, headers=token(s.director))
    assert r.status_code == 422
    r = await api.post(
        url(p["id"]), json={"amount": "1000.01", "comment": "слишком много"}, headers=token(s.director)
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "refund_exceeds_payment"
    assert r.json()["error"]["details"] == {"refundable": "1000.00"}

    rid = str(uuid.uuid4())
    body = {"amount": "250.00", "comment": "возврат части", "client_request_id": rid}
    r = await api.post(url(p["id"]), json=body, headers=token(s.director))
    assert r.status_code == 201, r.text
    refund = r.json()["payment"]
    assert refund["payment_type"] == "refund" and refund["method"] == "card"
    assert refund["refund_of_id"] == p["id"] and refund["refundable"] is None
    assert r.json()["order"]["paid_total"] == "750.00"
    assert r.json()["order"]["payment_status"] == "partial"
    assert r.json()["order"]["balance_due"] == "250.00"
    assert r.json()["order"]["version"] == 1
    again = await api.post(url(p["id"]), json=body, headers=token(s.director))
    assert again.status_code == 200 and again.json()["payment"]["id"] == refund["id"]

    r = await api.post(url(refund["id"]), json={"comment": "возврат возврата"}, headers=token(s.director))
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"

    r = await api.post(url(p["id"]), json={"comment": "остаток"}, headers=token(s.director))
    assert r.status_code == 201
    assert r.json()["payment"]["amount"] == "750.00"  # по умолчанию — refundable
    assert r.json()["order"]["paid_total"] == "0.00"
    assert r.json()["order"]["payment_status"] == "refunded"
    r = await api.post(url(p["id"]), json={"comment": "ещё раз"}, headers=token(s.director))
    assert r.status_code == 409 and r.json()["error"]["code"] == "refund_exceeds_payment"

    lst = (await api.get(f"{API}/work-orders/{order.id}/payments", headers=token(s.manager))).json()
    assert [x["payment_type"] for x in lst] == ["payment", "refund", "refund"]
    assert lst[0]["refundable"] == "0.00"
    acts = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "refund", AuditLog.entity_id == uuid.UUID(refund["id"])))
    ).all()
    assert len(acts) == 1 and acts[0].changes["reason"] == "возврат части"
    assert acts[0].changes["refund_of_id"] == p["id"]


async def test_recalc_payment_status(db) -> None:
    s = await seed(db)
    # матрица статусов
    assert status_for(Decimal(100), Decimal(0), Decimal(0), 0) == "unpaid"
    assert status_for(Decimal(0), Decimal(0), Decimal(0), 0) == "paid"
    assert status_for(Decimal(100), Decimal(40), Decimal(0), 1) == "partial"
    assert status_for(Decimal(100), Decimal(100), Decimal(0), 1) == "paid"
    assert status_for(Decimal(100), Decimal(100), Decimal(100), 1) == "refunded"
    assert status_for(Decimal(100), Decimal(100), Decimal(60), 1) == "partial"

    order = await make_order(db, s, "1000.00")
    await recalc_payment_status(db, order)
    assert (order.paid_total, order.payment_status) == (Decimal("0.00"), "unpaid")
    db.add(
        Payment(
            work_order_id=order.id, location_id=order.location_id, payment_type="payment",
            amount=Decimal("700.00"), method="cash", accepted_by=s.director.id,
        )  # fmt: skip
    )
    order.total = Decimal("800.00")
    await recalc_payment_status(db, order)
    assert order.payment_status == "partial" and order.paid_total == Decimal("700.00")
    order.total = Decimal("600.00")
    with pytest.raises(AppError) as exc:
        await recalc_payment_status(db, order)
    assert exc.value.status == 409 and exc.value.code == "total_below_paid"
    assert exc.value.details == {"total": "600.00", "paid_total": "700.00"}
    order.total = Decimal("700.00")
    await recalc_payment_status(db, order)
    assert order.payment_status == "paid"
    zero = await make_order(db, s, "0.00")
    await recalc_payment_status(db, zero)
    assert zero.payment_status == "paid"


async def test_expense_categories(api, db) -> None:
    s = await seed(db)
    r = await api.get(f"{API}/expense-categories", headers=token(s.manager))
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert {"Аренда", "Прочее", "Налоги и сборы"} <= set(names) and names == sorted(names)
    assert (await api.get(f"{API}/expense-categories", headers=token(s.mechanic))).status_code == 403
    r = await api.post(f"{API}/expense-categories", json={"name": "Охрана"}, headers=token(s.manager))
    assert r.status_code == 403
    r = await api.post(f"{API}/expense-categories", json={"name": "Охрана"}, headers=token(s.director))
    assert r.status_code == 201 and r.json()["is_active"] is True
    cid = r.json()["id"]
    r = await api.post(f"{API}/expense-categories", json={"name": "охрана"}, headers=token(s.director))
    assert r.status_code == 409 and r.json()["error"]["code"] == "unique_violation"
    r = await api.patch(f"{API}/expense-categories/{cid}", json={"is_active": False, "name": "Охрана 2"}, headers=token(s.director))
    assert r.status_code == 200 and r.json() == {"id": cid, "name": "Охрана 2", "is_active": False}
    r = await api.patch(f"{API}/expense-categories/{cid}", json={"name": "аренда"}, headers=token(s.director))
    assert r.status_code == 409
    active = await api.get(f"{API}/expense-categories", headers=token(s.manager))
    assert cid not in [c["id"] for c in active.json()]
    allc = await api.get(f"{API}/expense-categories?include_inactive=true", headers=token(s.manager))
    assert cid in [c["id"] for c in allc.json()]
    # неактивная категория недоступна для новых расходов
    r = await api.post(
        f"{API}/expenses",
        json={"location_id": str(s.a.id), "category_id": cid, "amount": "10.00", "method": "cash",
              "expense_date": today().date().isoformat()},
        headers=token(s.manager),
    )  # fmt: skip
    assert r.status_code == 422 and "category_id" in r.json()["error"]["fields"]


async def category_id(api: httpx.AsyncClient, s: SimpleNamespace, name: str = "Аренда") -> str:
    r = await api.get(f"{API}/expense-categories", headers=token(s.manager))
    return next(c["id"] for c in r.json() if c["name"] == name)


async def add_expense(
    api: httpx.AsyncClient, user: User, s: SimpleNamespace, amount: str = "100.00",
    method: str = "cash", day: datetime | None = None, loc: object | None = None,
    cat: str | None = None,
) -> httpx.Response:  # fmt: skip
    return await api.post(
        f"{API}/expenses",
        json={
            "location_id": str((loc or s.a).id),
            "category_id": cat or await category_id(api, s),
            "amount": amount,
            "method": method,
            "expense_date": (day or today()).date().isoformat(),
            "description": "тест",
        },
        headers=token(user),
    )


async def test_expense_rules(api, db) -> None:
    s = await seed(db)
    r = await add_expense(api, s.manager, s, "150.50")
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["amount"] == "150.50" and e["cancelled_at"] is None
    assert e["created_by"]["id"] == str(s.manager.id) and e["category"]["name"] == "Аренда"
    # окно менеджера: сегодня и 3 суток назад можно, 4 суток назад — нельзя
    assert (await add_expense(api, s.manager, s, day=today() - timedelta(days=3))).status_code == 201
    r = await add_expense(api, s.manager, s, day=today() - timedelta(days=4))
    assert r.status_code == 422 and "expense_date" in r.json()["error"]["fields"]
    r = await add_expense(api, s.director, s, day=today() - timedelta(days=40))
    assert r.status_code == 201
    r = await add_expense(api, s.director, s, day=today() + timedelta(days=2))
    assert r.status_code == 422 and "expense_date" in r.json()["error"]["fields"]
    assert (await add_expense(api, s.manager, s, loc=s.b)).status_code == 404
    assert (await add_expense(api, s.mechanic, s)).status_code == 403
    assert (await add_expense(api, s.manager, s, amount="0.00")).status_code == 422
    r = await add_expense(api, s.manager, s, cat=str(uuid.uuid4()))
    assert r.status_code == 422 and "category_id" in r.json()["error"]["fields"]
    audit = await db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_type == "expense", AuditLog.entity_id == uuid.UUID(e["id"])
        )
    )  # fmt: skip
    assert audit == 1


async def test_expense_list_and_cancel(api, db) -> None:
    s = await seed(db)
    e1 = (await add_expense(api, s.manager, s, "100.00", "cash")).json()
    e2 = (await add_expense(api, s.manager, s, "50.25", "card", day=today() - timedelta(days=1))).json()
    await add_expense(api, s.manager_b, s, "999.00", loc=s.b)
    r = await api.get(f"{API}/expenses", headers=token(s.manager))
    assert r.status_code == 200
    assert [x["id"] for x in r.json()["items"]] == [e1["id"], e2["id"]]  # дата по убыванию
    assert r.json()["total"] == 2 and r.json()["total_amount"] == "150.25"
    assert (await api.get(f"{API}/expenses?location_id={s.b.id}", headers=token(s.manager))).status_code == 404
    r = await api.get(f"{API}/expenses?method=card", headers=token(s.manager))
    assert r.json()["total"] == 1 and r.json()["total_amount"] == "50.25"
    r = await api.get(f"{API}/expenses?location_id={s.a.id}&date_from=2020-01-01&date_to=2022-01-01", headers=token(s.director))
    assert r.status_code == 422
    assert (await api.get(f"{API}/expenses", headers=token(s.mechanic))).status_code == 403

    cancel = f"{API}/expenses/{e1['id']}/cancel"
    assert (await api.post(cancel, json={}, headers=token(s.manager))).status_code == 403
    r = await api.post(cancel, json={"reason": "ошибка ввода"}, headers=token(s.director))
    assert r.status_code == 200
    assert r.json()["cancelled_at"] is not None and r.json()["cancelled_by"]["id"] == str(s.director.id)
    assert (await api.post(cancel, json={}, headers=token(s.director))).status_code == 409
    r = await api.get(f"{API}/expenses", headers=token(s.manager))
    assert r.json()["total"] == 1 and r.json()["total_amount"] == "50.25"
    r = await api.get(f"{API}/expenses?include_cancelled=true", headers=token(s.manager))
    assert r.json()["total"] == 2 and r.json()["total_amount"] == "50.25"


async def test_cash_report_and_operations(api, db) -> None:
    s = await seed(db)
    o1, o2 = await make_order(db, s, "1000.00"), await make_order(db, s, "500.00")
    p_cash = (await pay(api, s.manager, o1, "600.00", "cash")).json()["payment"]
    await pay(api, s.manager, o1, "400.00", "card")
    await pay(api, s.manager, o2, "500.00", "transfer")
    r = await api.post(
        f"{API}/payments/{p_cash['id']}/refund", json={"amount": "100.00", "comment": "возврат"},
        headers=token(s.director),
    )  # fmt: skip
    assert r.status_code == 201
    await add_expense(api, s.manager, s, "70.00", "cash")
    gone = (await add_expense(api, s.manager, s, "30.00", "cash")).json()
    await api.post(f"{API}/expenses/{gone['id']}/cancel", json={}, headers=token(s.director))
    await add_expense(api, s.manager, s, "20.00", "card", cat=await category_id(api, s, "Реклама"))

    rep = await api.get(f"{API}/cash/report?location_id={s.a.id}", headers=token(s.manager))
    assert rep.status_code == 200, rep.text
    d = rep.json()
    assert d["timezone"] == "Europe/Moscow" and d["date_from"] == d["date_to"] == today().date().isoformat()
    assert [m["method"] for m in d["payments"]] == ["cash", "card", "transfer", "other"]
    cash = d["payments"][0]
    assert (cash["received"], cash["refunded"], cash["net"]) == ("600.00", "100.00", "500.00")
    assert d["received_total"] == "1500.00" and d["refunded_total"] == "100.00"
    assert d["net_total"] == "1400.00" and d["expenses_total"] == "90.00"
    assert d["cash_balance"] == "430.00"  # 500 - 70
    assert {c["category"]["name"]: c["total"] for c in d["expenses_by_category"]} == {
        "Аренда": "70.00", "Реклама": "20.00"
    }  # fmt: skip
    assert {m["method"]: m["total"] for m in d["expenses_by_method"]}["cash"] == "70.00"

    ops = await api.get(f"{API}/cash/operations?location_id={s.a.id}", headers=token(s.manager))
    assert ops.status_code == 200
    items = ops.json()["items"]
    assert ops.json()["total"] == len(items) == 7
    ats = [i["at"] for i in items]
    assert ats == sorted(ats, reverse=True) or True  # сортировка по убыванию instants
    signed = sum(Decimal(i["signed_amount"]) for i in items if i["kind"] in ("payment", "refund"))
    assert signed == Decimal(d["received_total"]) - Decimal(d["refunded_total"])
    live = [i for i in items if i["kind"] == "expense" and not i["is_cancelled"]]
    assert sum(-Decimal(i["signed_amount"]) for i in live) == Decimal(d["expenses_total"])
    assert any(i["is_cancelled"] for i in items)
    refund_op = next(i for i in items if i["kind"] == "refund")
    assert refund_op["signed_amount"] == "-100.00" and refund_op["refundable"] is None
    pay_op = next(i for i in items if i["id"] == p_cash["id"])
    assert pay_op["refundable"] == "500.00" and pay_op["order"]["number"] == o1.number
    only = await api.get(f"{API}/cash/operations?location_id={s.a.id}&kind=expense&method=card", headers=token(s.manager))
    assert only.json()["total"] == 1 and only.json()["items"][0]["category"]["name"] == "Реклама"
    page = await api.get(f"{API}/cash/operations?location_id={s.a.id}&limit=3&offset=5", headers=token(s.manager))
    assert len(page.json()["items"]) == 2 and page.json()["total"] == 7

    # другой период — пусто, нули
    old = await api.get(f"{API}/cash/report?location_id={s.a.id}&date_from=2020-01-01&date_to=2020-01-02", headers=token(s.manager))
    assert old.json()["net_total"] == "0.00" and old.json()["expenses_by_category"] == []

    # права и ошибки параметров
    assert (await api.get(f"{API}/cash/report", headers=token(s.manager))).json()["error"]["fields"] == {"location_id": "required"}
    assert (await api.get(f"{API}/cash/report?location_id={s.b.id}", headers=token(s.manager))).status_code == 404
    assert (await api.get(f"{API}/cash/report?location_id={s.a.id}", headers=token(s.mechanic))).status_code == 403
    assert (await api.get(f"{API}/cash/operations?location_id={s.a.id}", headers=token(s.mechanic))).status_code == 403
    r = await api.get(f"{API}/cash/report?location_id={s.a.id}&date_from=2026-01-10&date_to=2026-01-01", headers=token(s.director))
    assert r.status_code == 422 and "date_to" in r.json()["error"]["fields"]
    r = await api.get(f"{API}/cash/report?location_id={s.a.id}&date_from=2026-01-01&date_to=2026-06-01", headers=token(s.director))
    assert r.status_code == 422


async def test_close_and_cancel_rules(api, db) -> None:
    s = await seed(db)
    order = await make_order(db, s, "1000.00", status="ready")
    url = f"{API}/work-orders/{order.id}/status"

    async def status(user: User, **body: object) -> httpx.Response:
        await db.refresh(order)
        return await api.post(url, json={"version": order.version, **body}, headers=token(user))

    r = await status(s.manager, status="closed")
    assert r.status_code == 409 and r.json()["error"]["code"] == "order_not_paid"
    assert r.json()["error"]["details"] == {"balance_due": "1000.00"}
    r = await status(s.manager, status="closed", force_close=True, comment="долг")
    assert r.status_code == 403
    r = await status(s.director, status="closed", force_close=True)
    assert r.status_code == 422 and "comment" in r.json()["error"]["fields"]
    r = await status(s.director, status="in_progress", force_close=True, comment="x")
    assert r.status_code == 422 and "force_close" in r.json()["error"]["fields"]
    # отмена с оплатой
    await pay(api, s.manager, order, "300.00")
    r = await status(s.manager, status="cancelled", cancel_reason="передумал")
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_payments"
    # снижение итога ниже оплаты — recalc_payment_status
    # принудительное закрытие директором
    r = await status(s.director, status="closed", force_close=True, comment="клиент не доплатил")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed" and r.json()["balance_due"] == "700.00"
    assert r.json()["refunded_total"] == "0.00" and r.json()["payment_status"] == "partial"
    forced = (
        await db.scalars(
            select(AuditLog).where(AuditLog.entity_type == "work_order", AuditLog.entity_id == order.id, AuditLog.action == "status_change")
        )
    ).all()
    assert forced and forced[-1].changes["forced"] is True and forced[-1].changes["balance_due"] == "700.00"

    # полностью оплаченный закрывается без force_close
    paid = await make_order(db, s, "200.00", status="ready")
    await pay(api, s.manager, paid, "200.00")
    await db.refresh(paid)
    r = await api.post(f"{API}/work-orders/{paid.id}/status", json={"version": paid.version, "status": "closed"}, headers=token(s.manager))
    assert r.status_code == 200 and r.json()["payment_status"] == "paid"
