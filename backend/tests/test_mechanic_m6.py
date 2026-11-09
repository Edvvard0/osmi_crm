"""Модуль 6: рабочее место механика — задачи, таймер, заявки на запчасти, рекомендации, reopen."""

import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import Client, Part, Role, User, Vehicle
from app.models.mechanic import WorkLog
from app.models.stock import StockBalance
from app.models.work_order import WorkOrder, WorkOrderItem
from app.services import timers
from tests.factories import bearer, make_location, make_user

API = "/api/v1"

pytestmark = pytest.mark.integration


def tok(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


async def seed(db: AsyncSession) -> SimpleNamespace:
    a = await make_location(db)
    b = await make_location(db)
    manager = await make_user(db, Role.manager, locations=[a])
    manager_b = await make_user(db, Role.manager, locations=[b])
    director = await make_user(db, Role.director)
    mech = await make_user(db, Role.mechanic, locations=[a])
    mech2 = await make_user(db, Role.mechanic, locations=[a])
    mech_b = await make_user(db, Role.mechanic, locations=[b])
    client = Client(
        client_type="person", full_name="Иван Петров", phone="+79" + str(uuid.uuid4().int)[:9]
    )
    db.add(client)
    await db.flush()
    vehicle = Vehicle(client_id=client.id, make="Kia", model="Rio", plate_number="A123BC")
    part = Part(
        sku=f"SKU-{uuid.uuid4().hex[:8]}",
        name="Масляный фильтр Mann",
        unit="pcs",
        department="both",
        sale_price=Decimal("500.00"),
    )
    db.add_all([vehicle, part])
    await db.flush()
    db.add(
        StockBalance(location_id=a.id, part_id=part.id, quantity=Decimal(10), avg_cost=Decimal(100))
    )
    await db.commit()
    return SimpleNamespace(
        a=a, b=b, manager=manager, manager_b=manager_b, director=director, mech=mech,
        mech2=mech2, mech_b=mech_b, client=client, vehicle=vehicle, part=part,
    )  # fmt: skip


async def make_order(
    db: AsyncSession,
    s: SimpleNamespace,
    mechanics: list[User | None],
    status: str = "in_progress",
    location: object | None = None,
) -> SimpleNamespace:
    loc = location or s.a
    order = WorkOrder(
        number=f"T-{uuid.uuid4().hex[:8]}",
        location_id=loc.id,
        client_id=s.client.id,
        vehicle_id=s.vehicle.id,
        department="service",
        status=status,
        manager_id=s.manager.id,
        complaint="Стук в подвеске",
    )
    db.add(order)
    await db.flush()
    items = []
    for i, mech in enumerate(mechanics):
        item = WorkOrderItem(
            work_order_id=order.id,
            name=f"Работа {i + 1}",
            department="service",
            quantity=Decimal(1),
            unit_price=Decimal("1000.00"),
            total=Decimal("1000.00"),
            norm_hours=Decimal("1.50"),
            mechanic_id=mech.id if mech else None,
            sort_order=i,
        )
        db.add(item)
        items.append(item)
    await db.commit()
    return SimpleNamespace(order=order, items=items)


async def order_state(db: AsyncSession, order_id: uuid.UUID) -> tuple[str, int]:
    row = (
        await db.execute(
            select(WorkOrder.status, WorkOrder.version)
            .where(WorkOrder.id == order_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    return row[0], row[1]


async def test_access_and_visibility(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech, s.mech2, None])
    mine, foreign, free = (i.id for i in o.items)

    r = await api.get(f"{API}/mechanic/tasks", headers=tok(s.mech))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["item_id"] for t in body["items"]] == [str(mine)]
    assert body["active"] is None
    task = body["items"][0]
    assert task["can_start"] is True and task["order_number"] == o.order.number
    assert "unit_price" not in task and "total" not in task  # цены механику не отдаются

    d = await api.get(f"{API}/mechanic/tasks/{mine}", headers=tok(s.mech))
    assert d.status_code == 200 and d.json()["complaint"] == "Стук в подвеске"
    assert "unit_price" not in str(d.json())
    for iid in (foreign, free, uuid.uuid4()):
        assert (
            await api.get(f"{API}/mechanic/tasks/{iid}", headers=tok(s.mech))
        ).status_code == 404
    # механик другой точки не видит чужую позицию
    assert (await api.get(f"{API}/mechanic/tasks/{mine}", headers=tok(s.mech_b))).status_code == 404
    # менеджер и директор на /mechanic/* — 403, без токена — 401
    for u in (s.manager, s.director):
        assert (await api.get(f"{API}/mechanic/tasks", headers=tok(u))).status_code == 403
    assert (await api.get(f"{API}/mechanic/tasks")).status_code == 401


async def test_start_pause_finish_and_auto_move(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    item = o.items[0]
    base = f"{API}/mechanic/tasks/{item.id}"

    r = await api.post(f"{base}/start", json={}, headers=tok(s.mech))
    assert r.status_code == 200, r.text
    assert r.json()["task"]["status"] == "in_progress" and r.json()["active"]["item_id"] == str(
        item.id
    )
    assert r.json()["task"]["running_since"] is not None
    # повторный старт той же работы идемпотентен (один открытый интервал)
    assert (await api.post(f"{base}/start", json={}, headers=tok(s.mech))).status_code == 200
    n_open = (
        await db.execute(
            select(WorkLog).where(WorkLog.item_id == item.id, WorkLog.ended_at.is_(None))
        )
    ).all()
    assert len(n_open) == 1

    p = await api.post(f"{base}/pause", json={}, headers=tok(s.mech))
    assert (
        p.status_code == 200
        and p.json()["task"]["status"] == "paused"
        and p.json()["active"] is None
    )
    assert (await api.post(f"{base}/pause", json={}, headers=tok(s.mech))).status_code == 409

    # 90 секунд работы -> ROUND_HALF_UP(1.5) = 2 минуты
    assert (await api.post(f"{base}/start", json={}, headers=tok(s.mech))).status_code == 200
    await db.execute(
        text("UPDATE work_logs SET started_at = :t WHERE item_id = :i AND ended_at IS NULL"),
        {"t": timers.now() - timedelta(seconds=90), "i": item.id},
    )
    await db.commit()
    f = await api.post(f"{base}/finish", json={"comment": "Готово"}, headers=tok(s.mech))
    assert f.status_code == 200, f.text
    fj = f.json()
    assert fj["task"]["status"] == "done" and fj["order_auto_moved"] is True
    assert fj["order_status"] == "quality_check" and fj["active"] is None
    minutes = await db.scalar(
        select(WorkOrderItem.actual_minutes)
        .where(WorkOrderItem.id == item.id)
        .execution_options(populate_existing=True)
    )
    assert minutes >= 2
    assert await order_state(db, o.order.id) == ("quality_check", 2)
    # завершённую работу нельзя стартовать; повторное завершение идемпотентно
    assert (await api.post(f"{base}/start", json={}, headers=tok(s.mech))).status_code == 409
    again = await api.post(f"{base}/finish", json={}, headers=tok(s.mech))
    assert again.status_code == 200 and again.json()["order_auto_moved"] is False
    assert await order_state(db, o.order.id) == ("quality_check", 2)


async def test_one_active_task_and_pause_active(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech, s.mech])
    a, b = o.items
    assert (
        await api.post(f"{API}/mechanic/tasks/{a.id}/start", json={}, headers=tok(s.mech))
    ).status_code == 200

    r = await api.post(f"{API}/mechanic/tasks/{b.id}/start", json={}, headers=tok(s.mech))
    assert r.status_code == 409 and r.json()["error"]["code"] == "another_task_active"
    assert r.json()["error"]["details"]["item_id"] == str(a.id)

    r = await api.post(
        f"{API}/mechanic/tasks/{b.id}/start", json={"pause_active": True}, headers=tok(s.mech)
    )
    assert r.status_code == 200, r.text
    assert r.json()["active"]["item_id"] == str(b.id)
    lst = (await api.get(f"{API}/mechanic/tasks", headers=tok(s.mech))).json()
    assert lst["active"]["item_id"] == str(b.id)
    st = {t["item_id"]: t["status"] for t in lst["items"]}
    assert st == {str(a.id): "paused"}  # активная работа в items не дублируется
    # завершение первой работы при незавершённой второй не двигает заказ
    f = await api.post(f"{API}/mechanic/tasks/{a.id}/finish", json={}, headers=tok(s.mech))
    assert f.status_code == 200 and f.json()["order_auto_moved"] is False
    assert await order_state(db, o.order.id) == ("in_progress", 1)


async def test_order_not_workable_and_cancelled(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech], status="new")
    r = await api.post(f"{API}/mechanic/tasks/{o.items[0].id}/start", json={}, headers=tok(s.mech))
    assert r.status_code == 409 and r.json()["error"]["code"] == "order_not_workable"

    o2 = await make_order(db, s, [s.mech])
    await db.execute(
        text("UPDATE work_order_items SET status='cancelled' WHERE id=:i"), {"i": o2.items[0].id}
    )
    await db.commit()
    r = await api.post(f"{API}/mechanic/tasks/{o2.items[0].id}/start", json={}, headers=tok(s.mech))
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
    # отменённая позиция скрыта из детали
    assert (
        await api.get(f"{API}/mechanic/tasks/{o2.items[0].id}", headers=tok(s.mech))
    ).status_code == 404


async def test_comments(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    iid = o.items[0].id
    r = await api.post(
        f"{API}/mechanic/tasks/{iid}/comments",
        json={"text": "Нужен подъёмник"},
        headers=tok(s.mech),
    )
    assert r.status_code == 201 and r.json()["text"] == "Нужен подъёмник"
    d = (await api.get(f"{API}/mechanic/tasks/{iid}", headers=tok(s.mech))).json()
    assert [c["text"] for c in d["comments"]] == ["Нужен подъёмник"]
    bad = await api.post(
        f"{API}/mechanic/tasks/{iid}/comments", json={"text": "   "}, headers=tok(s.mech)
    )
    assert bad.status_code == 422
    other = await api.post(
        f"{API}/mechanic/tasks/{iid}/comments", json={"text": "x"}, headers=tok(s.mech2)
    )
    assert other.status_code == 404


async def test_part_request_create_and_list(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    iid = str(o.items[0].id)
    h = tok(s.mech)

    r = await api.post(
        f"{API}/mechanic/part-requests", json={"item_id": iid, "part_id": str(s.part.id)}, headers=h
    )
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["status"] == "new" and j["quantity"] == "1.000" and j["description"] == s.part.name
    assert j["unit"] == "pcs" and j["order_number"] == o.order.number

    r2 = await api.post(
        f"{API}/mechanic/part-requests",
        json={"item_id": iid, "description": "Тормозные колодки", "quantity": "2.5"},
        headers=h,
    )
    assert r2.status_code == 201 and r2.json()["quantity"] == "2.500" and r2.json()["part"] is None
    # ни детали, ни описания -> 422; число вместо строки -> 422; чужая позиция -> 404
    assert (
        await api.post(f"{API}/mechanic/part-requests", json={"item_id": iid}, headers=h)
    ).status_code == 422
    assert (
        await api.post(
            f"{API}/mechanic/part-requests",
            json={"item_id": iid, "description": "x", "quantity": 2},
            headers=h,
        )
    ).status_code == 422
    assert (
        await api.post(
            f"{API}/mechanic/part-requests",
            json={"item_id": iid, "description": "x"},
            headers=tok(s.mech2),
        )
    ).status_code == 404

    lst = (await api.get(f"{API}/mechanic/part-requests", headers=h)).json()
    assert lst["total"] == 2 and lst["items"][0]["id"] == r2.json()["id"]  # новые сверху
    assert (await api.get(f"{API}/mechanic/part-requests?status=issued", headers=h)).json()[
        "total"
    ] == 0
    assert (await api.get(f"{API}/mechanic/part-requests", headers=tok(s.mech2))).json()[
        "total"
    ] == 0


async def test_manager_approve_reject_summary(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    iid = str(o.items[0].id)
    ids = []
    for _ in range(3):
        r = await api.post(
            f"{API}/mechanic/part-requests",
            json={"item_id": iid, "part_id": str(s.part.id)},
            headers=tok(s.mech),
        )
        ids.append(r.json()["id"])
    m = tok(s.manager)

    sm = (await api.get(f"{API}/part-requests/summary", headers=m)).json()
    assert sm == {"new": 3, "approved": 0}
    lst = (await api.get(f"{API}/part-requests?status=new", headers=m)).json()
    assert lst["total"] == 3
    first = lst["items"][0]
    assert first["part"]["in_stock"] == "10.000" and first["order"]["number"] == o.order.number
    assert first["mechanic"]["id"] == str(s.mech.id)

    ap = await api.post(f"{API}/part-requests/{ids[0]}/approve", json={}, headers=m)
    assert (
        ap.status_code == 200
        and ap.json()["status"] == "approved"
        and ap.json()["handled_by"]["id"] == str(s.manager.id)
    )
    assert (
        await api.post(f"{API}/part-requests/{ids[0]}/approve", json={}, headers=m)
    ).status_code == 409
    assert (await api.get(f"{API}/part-requests/summary", headers=m)).json() == {
        "new": 2,
        "approved": 1,
    }

    assert (
        await api.post(f"{API}/part-requests/{ids[1]}/reject", json={}, headers=m)
    ).status_code == 422
    rj = await api.post(
        f"{API}/part-requests/{ids[1]}/reject", json={"reason": "Нет в наличии"}, headers=m
    )
    assert (
        rj.status_code == 200
        and rj.json()["status"] == "rejected"
        and rj.json()["reject_reason"] == "Нет в наличии"
    )
    assert (
        await api.post(f"{API}/part-requests/{ids[1]}/reject", json={"reason": "ещё"}, headers=m)
    ).status_code == 409
    mine = (
        await api.get(f"{API}/mechanic/part-requests?status=rejected", headers=tok(s.mech))
    ).json()
    assert mine["items"][0]["reject_reason"] == "Нет в наличии"

    # менеджер другой точки -> 404; механику менеджерские эндпоинты недоступны
    assert (
        await api.post(f"{API}/part-requests/{ids[2]}/approve", json={}, headers=tok(s.manager_b))
    ).status_code == 404
    assert (await api.get(f"{API}/part-requests", headers=tok(s.mech))).status_code == 403
    assert (
        await api.get(f"{API}/part-requests?location_id={s.b.id}", headers=m)
    ).status_code == 404


async def test_issue_part_request(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    iid = str(o.items[0].id)
    m = tok(s.manager)
    rid = (
        await api.post(
            f"{API}/mechanic/part-requests",
            json={"item_id": iid, "part_id": str(s.part.id), "quantity": "2"},
            headers=tok(s.mech),
        )
    ).json()["id"]

    # устаревшая версия -> version_conflict с актуальной
    bad = await api.post(f"{API}/part-requests/{rid}/issue", json={"version": 99}, headers=m)
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "version_conflict"
    assert bad.json()["error"]["details"]["current_version"] == "1"
    assert (await api.get(f"{API}/mechanic/part-requests", headers=tok(s.mech))).json()["items"][0][
        "status"
    ] == "new"

    ok = await api.post(f"{API}/part-requests/{rid}/issue", json={"version": 1}, headers=m)
    assert ok.status_code == 200, ok.text
    j = ok.json()
    assert j["request"]["status"] == "issued" and j["order"]["version"] == 2
    assert j["order"]["parts"][0]["quantity"] == "2.000"
    assert (
        await api.post(f"{API}/part-requests/{rid}/issue", json={"version": 2}, headers=m)
    ).status_code == 409
    qty = await db.scalar(
        select(StockBalance.quantity)
        .where(StockBalance.part_id == s.part.id)
        .execution_options(populate_existing=True)
    )
    assert qty == Decimal("8.000")

    # заявка без детали: нужна part_id -> 422
    free = (
        await api.post(
            f"{API}/mechanic/part-requests",
            json={"item_id": iid, "description": "Хомут"},
            headers=tok(s.mech),
        )
    ).json()["id"]
    r = await api.post(f"{API}/part-requests/{free}/issue", json={"version": 2}, headers=m)
    assert r.status_code == 422 and r.json()["error"]["fields"].get("part_id")


async def test_reopen(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    item = o.items[0]
    base = f"{API}/mechanic/tasks/{item.id}"
    assert (await api.post(f"{base}/start", json={}, headers=tok(s.mech))).status_code == 200
    assert (await api.post(f"{base}/finish", json={}, headers=tok(s.mech))).status_code == 200
    assert await order_state(db, o.order.id) == ("quality_check", 2)

    url = f"{API}/work-orders/{o.order.id}/items/{item.id}/reopen"
    assert (await api.post(url, json={"version": 2}, headers=tok(s.mech))).status_code == 403
    assert (await api.post(url, json={"version": 1}, headers=tok(s.manager))).status_code == 409
    assert (await api.post(url, json={"version": 2}, headers=tok(s.manager_b))).status_code == 404

    r = await api.post(url, json={"version": 2}, headers=tok(s.manager))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress" and r.json()["version"] == 3
    st = await db.scalar(
        select(WorkOrderItem.status)
        .where(WorkOrderItem.id == item.id)
        .execution_options(populate_existing=True)
    )
    assert st == "paused"
    # позиция уже не done -> invalid_state
    again = await api.post(url, json={"version": 3}, headers=tok(s.director))
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"
    # закрытый заказ -> invalid_state
    await db.execute(text("UPDATE work_orders SET status='closed' WHERE id=:i"), {"i": o.order.id})
    await db.commit()
    closed = await api.post(url, json={"version": 3}, headers=tok(s.manager))
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "invalid_state"


async def test_recommendations(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    o = await make_order(db, s, [s.mech])
    other = await make_order(db, s, [s.mech])
    r = await api.post(
        f"{API}/mechanic/recommendations",
        json={"item_id": str(o.items[0].id), "text": "Заменить сальники"},
        headers=tok(s.mech),
    )
    assert r.status_code == 201, r.text
    rec = r.json()
    assert (
        rec["priority"] == "medium"
        and rec["status"] == "open"
        and rec["work_order_number"] == o.order.number
    )
    assert rec["created_by"]["id"] == str(s.mech.id)
    assert (
        await api.post(
            f"{API}/mechanic/recommendations",
            json={"item_id": str(o.items[0].id), "text": ""},
            headers=tok(s.mech),
        )
    ).status_code == 422
    assert (
        await api.post(
            f"{API}/mechanic/recommendations",
            json={"item_id": str(o.items[0].id), "text": "x"},
            headers=tok(s.mech2),
        )
    ).status_code == 404

    m = tok(s.manager)
    vid = s.vehicle.id
    lst = await api.get(f"{API}/vehicles/{vid}/recommendations", headers=m)
    assert lst.status_code == 200 and [x["id"] for x in lst.json()] == [rec["id"]]
    assert (
        await api.get(f"{API}/vehicles/{uuid.uuid4()}/recommendations", headers=m)
    ).status_code == 404

    c = await api.post(
        f"{API}/vehicles/{vid}/recommendations",
        json={"text": "Шиномонтаж", "priority": "high", "work_order_id": str(other.order.id)},
        headers=m,
    )
    assert c.status_code == 201 and c.json()["priority"] == "high"
    assert (
        await api.post(
            f"{API}/vehicles/{vid}/recommendations",
            json={"text": "x", "priority": "urgent"},
            headers=m,
        )
    ).status_code == 422
    assert (
        await api.post(
            f"{API}/vehicles/{vid}/recommendations",
            json={"text": "x", "priority": "low", "work_order_id": str(uuid.uuid4())},
            headers=m,
        )
    ).status_code == 422

    p = await api.patch(
        f"{API}/recommendations/{rec['id']}",
        json={"status": "done", "work_order_id": str(other.order.id)},
        headers=m,
    )
    assert (
        p.status_code == 200
        and p.json()["status"] == "done"
        and p.json()["work_order_number"] == other.order.number
    )
    back = await api.patch(f"{API}/recommendations/{rec['id']}", json={"status": "open"}, headers=m)
    assert back.status_code == 200 and back.json()["status"] == "open"
    assert (
        await api.patch(f"{API}/recommendations/{rec['id']}", json={"status": "bogus"}, headers=m)
    ).status_code == 422
    assert (
        await api.patch(f"{API}/recommendations/{uuid.uuid4()}", json={"status": "done"}, headers=m)
    ).status_code == 404
    only_open = (
        await api.get(f"{API}/vehicles/{vid}/recommendations?status=done", headers=m)
    ).json()
    assert [x["id"] for x in only_open] == []
    assert (
        await api.get(f"{API}/vehicles/{vid}/recommendations", headers=tok(s.mech))
    ).status_code == 403


async def test_parts_search(api: httpx.AsyncClient, db: AsyncSession) -> None:
    s = await seed(db)
    h = tok(s.mech)
    r = await api.get(f"{API}/mechanic/parts?search=Масляный", headers=h)
    assert r.status_code == 200 and any(p["id"] == str(s.part.id) for p in r.json())
    assert "sale_price" not in r.json()[0]
    assert (await api.get(f"{API}/mechanic/parts?search=М", headers=h)).status_code == 422
    assert (
        await api.get(f"{API}/mechanic/parts?search=Масляный", headers=tok(s.manager))
    ).status_code == 403
