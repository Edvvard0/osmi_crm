"""Модуль 10: отчёты, дашборд, зарплата, тепловая карта активности, экспорт, сводка дня."""

import csv
import io
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import AuditLog, Client, Role, User, Vehicle
from app.models.cash import Expense, ExpenseCategory, Payment
from app.models.catalog import Part, Service, ServiceCategory
from app.models.mechanic import WorkLog
from app.models.payroll import PayrollScheme
from app.models.stock import StockBalance, StockMovement
from app.models.work_order import WorkOrder, WorkOrderItem, WorkOrderPart
from app.services import daily_summary
from app.services.report_export import export_limiter, safe_text
from tests.factories import bearer, make_location, make_user

API = "/api/v1"

pytestmark = pytest.mark.integration

MSK = ZoneInfo("Europe/Moscow")
D = Decimal


def token(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_export_limiter() -> None:
    export_limiter.reset()


# ---------------- набор данных ----------------
# Сентябрь 2026. Точка A (Москва, +3), точка B (Екатеринбург, +5).
#  O1  A  закрыт 10.09 12:00 МСК, скидка 10 %: работа 1000 (a1) + детейлинг 2000 (a2)
#          + запчасть 500; итого 3200
#  O2  A  закрыт 11.09 01:00 МСК (10.09 22:00 UTC!): работа 2 x 1000 (a1); итого 2000
#  O3  B  закрыт 12.09 10:00 ЕКТ: работа 5000 (b, без услуги) + запчасти 1000; итого 6000
#  O4  A  готов, не закрыт: работа 700 (a1, done) — в отчёты не входит
#  O6  A  закрыт 01.10 00:30 МСК (30.09 21:30 UTC) — вне сентября
# Выручка: A 5200, B 6000, всего 11200 за 3 заказа.


async def seed(db: AsyncSession) -> SimpleNamespace:
    a = await make_location(db, name="A-Точка", timezone="Europe/Moscow")
    b = await make_location(db, name="B-Точка", timezone="Asia/Yekaterinburg")
    director = await make_user(db, Role.director)
    manager_a = await make_user(db, Role.manager, locations=[a])
    manager_b = await make_user(db, Role.manager, locations=[b])
    a1 = await make_user(db, Role.mechanic, locations=[a])
    a2 = await make_user(db, Role.mechanic, locations=[a])
    mb = await make_user(db, Role.mechanic, locations=[b])
    client = Client(
        client_type="person", full_name="Иван Петров", phone="+79" + str(uuid.uuid4().int)[:9]
    )
    db.add(client)
    await db.flush()
    vehicle = Vehicle(client_id=client.id, make="Kia", model="Rio", plate_number="А001АА77")
    db.add(vehicle)
    cat = ServiceCategory(name="Категория", department="service")
    db.add(cat)
    await db.flush()
    s1 = Service(
        category_id=cat.id, code="S1" + uuid.uuid4().hex[:6], name="Замена масла",
        department="service", unit="pcs", base_price=D(1000), norm_hours=D("1.5"),
        duration_minutes=60,
    )  # fmt: skip
    s2 = Service(
        category_id=cat.id, code="S2" + uuid.uuid4().hex[:6], name="Полировка",
        department="detailing", unit="pcs", base_price=D(2000), norm_hours=D(2),
        duration_minutes=120,
    )  # fmt: skip
    p1 = Part(
        sku="P1" + uuid.uuid4().hex[:6],
        name="Фильтр",
        unit="pcs",
        department="service",
        sale_price=D(500),
    )
    p2 = Part(
        sku="P2" + uuid.uuid4().hex[:6],
        name="Колодки",
        unit="pcs",
        department="service",
        sale_price=D(500),
    )
    db.add_all([s1, s2, p1, p2])
    await db.flush()
    s = SimpleNamespace(
        a=a, b=b, director=director, manager_a=manager_a, manager_b=manager_b,
        a1=a1, a2=a2, mb=mb, client=client, vehicle=vehicle, s1=s1, s2=s2, p1=p1, p2=p2,
    )  # fmt: skip

    def order(
        loc: Any,
        status: str,
        closed: datetime | None,
        works: str,
        parts: str,
        disc: int,
        total: str,
    ):
        number = f"{loc.code}-{uuid.uuid4().hex[:8]}"
        o = WorkOrder(
            number=number, location_id=loc.id, client_id=client.id, vehicle_id=vehicle.id,
            department="service", status=status, manager_id=director.id,
            works_total=D(works), parts_total=D(parts), discount_percent=D(disc),
            discount_total=D(works) * disc / 100, total=D(total), closed_at=closed,
        )  # fmt: skip
        db.add(o)
        return o

    s.o1 = order(a, "closed", utc(2026, 9, 10, 9), "3000", "500", 10, "3200")
    s.o2 = order(a, "closed", utc(2026, 9, 10, 22), "2000", "0", 0, "2000")
    s.o3 = order(b, "closed", utc(2026, 9, 12, 5), "5000", "1000", 0, "6000")
    s.o4 = order(a, "ready", None, "700", "0", 0, "700")
    s.o6 = order(a, "closed", utc(2026, 9, 30, 21, 30), "999", "0", 0, "999")
    await db.flush()

    def item(
        o: Any,
        service: Any,
        name: str,
        dept: str,
        qty: int,
        price: str,
        norm: str,
        mech: Any,
        minutes: int,
    ):
        i = WorkOrderItem(
            work_order_id=o.id, service_id=service.id if service else None, name=name,
            department=dept,
            quantity=D(qty), unit_price=D(price), total=D(price) * qty, norm_hours=D(norm),
            mechanic_id=mech.id, status="done", finished_at=o.closed_at or utc(2026, 9, 12),
            actual_minutes=minutes,
        )  # fmt: skip
        db.add(i)
        return i

    s.i1 = item(s.o1, s1, "Замена масла", "service", 1, "1000", "1.5", a1, 90)
    s.i2 = item(s.o1, s2, "Полировка", "detailing", 1, "2000", "2", a2, 100)
    s.i3 = item(s.o2, s1, "Замена масла", "service", 2, "1000", "1", a1, 120)
    s.i4 = item(s.o3, None, "Диагностика", "service", 1, "5000", "3", mb, 150)
    s.i5 = item(s.o4, s1, "Замена масла", "service", 1, "700", "1", a1, 30)
    s.i6 = item(s.o6, s1, "Замена масла", "service", 1, "999", "1", a1, 30)
    await db.flush()
    # i3: total = цена x количество = 1000 x 2 (unit_price — за единицу)
    s.i3.unit_price = D(1000)
    s.i3.total = D(2000)

    def part(o: Any, p: Any, qty: str, price: str, cost: str, total: str):
        db.add(WorkOrderPart(
            work_order_id=o.id, part_id=p.id, name=p.name, sku=p.sku, unit="pcs", quantity=D(qty),
            unit_price=D(price), unit_cost=D(cost), total=D(total), added_by=director.id,
        ))  # fmt: skip

    part(s.o1, p1, "1", "500", "300", "500")
    part(s.o3, p2, "2", "500", "300", "1000")

    def pay(o: Any, loc: Any, kind: str, amount: str, when: datetime, ref: Payment | None = None):
        p = Payment(
            work_order_id=o.id, location_id=loc.id, payment_type=kind, amount=D(amount),
            method="cash",
            paid_at=when, accepted_by=director.id, comment="возврат" if kind == "refund" else None,
            refund_of_id=ref.id if ref else None,
        )  # fmt: skip
        db.add(p)
        return p

    pay1 = pay(s.o1, a, "payment", "3200", utc(2026, 9, 10, 9))
    await db.flush()
    pay(s.o1, a, "refund", "200", utc(2026, 9, 10, 10), pay1)
    pay(s.o3, b, "payment", "6000", utc(2026, 9, 12, 5))

    rent = ExpenseCategory(name="Т-Аренда")
    other = ExpenseCategory(name="Т-Прочее")
    db.add_all([rent, other])
    await db.flush()
    s.rent, s.other = rent, other

    def expense(loc: Any, cat: Any, amount: str, day: date, cancelled: bool = False):
        db.add(Expense(
            location_id=loc.id, category_id=cat.id, amount=D(amount), method="cash",
            expense_date=day,
            created_by=director.id, cancelled_at=utc(2026, 9, 30) if cancelled else None,
            cancelled_by=director.id if cancelled else None,
        ))  # fmt: skip

    expense(a, rent, "1000", date(2026, 9, 5))
    expense(a, other, "500", date(2026, 9, 20))
    expense(b, rent, "2000", date(2026, 9, 7))
    expense(a, other, "700", date(2026, 9, 21), cancelled=True)

    db.add(
        StockBalance(
            location_id=a.id, part_id=p1.id, quantity=D(10), avg_cost=D(300), min_quantity=D(0)
        )
    )
    db.add(
        StockBalance(
            location_id=b.id, part_id=p2.id, quantity=D(1), avg_cost=D(300), min_quantity=D(5)
        )
    )
    db.add(StockMovement(
        location_id=a.id, part_id=p1.id, movement_type="receipt", quantity=D(12), unit_cost=D(300),
        balance_after=D(12), created_by=director.id, created_at=utc(2026, 9, 3, 8),
    ))  # fmt: skip
    await db.commit()
    return s


def sep(**extra: Any) -> dict[str, Any]:
    return {"date_from": "2026-09-01", "date_to": "2026-09-30", **extra}


async def get(api: httpx.AsyncClient, path: str, user: User, **params: Any) -> httpx.Response:
    return await api.get(f"{API}{path}", params=params, headers=token(user))


def column(report: dict, key: str) -> list[str | None]:
    return [r[key] for r in report["rows"]]


def by(report: dict, key: str, value: str) -> dict:
    return next(r for r in report["rows"] if r[key] == value)


# ---------------- права ----------------

DIRECTOR_ONLY = [
    "/reports/dashboard",
    "/reports/revenue",
    "/reports/revenue/export",
    "/payroll",
    "/payroll/export",
    "/payroll/schemes",
    "/payroll/adjustments",
]


async def test_director_only_endpoints_are_forbidden_for_others(api, db) -> None:
    s = await seed(db)
    for path in DIRECTOR_ONLY:
        for user in (s.manager_a, s.a1):
            r = await get(api, path, user)
            assert r.status_code == 403, (path, user.role, r.text)
            assert r.json()["error"]["code"] == "forbidden"
        r = await api.get(f"{API}{path}")
        assert r.status_code == 401, path
    r = await get(api, f"/payroll/{s.a1.id}", s.manager_a, month="2026-09")
    assert r.status_code == 403
    for method, path, body in (
        ("POST", "/payroll/schemes", {}),
        ("POST", "/payroll/adjustments", {}),
        ("PATCH", f"/payroll/schemes/{uuid.uuid4()}", {}),
        ("DELETE", f"/payroll/schemes/{uuid.uuid4()}", None),
    ):
        r = await api.request(method, f"{API}{path}", json=body, headers=token(s.manager_a))
        assert r.status_code == 403, (method, path)


async def test_me_earnings_only_for_mechanic(api, db) -> None:
    s = await seed(db)
    for user in (s.director, s.manager_a):
        r = await get(api, "/me/earnings", user)
        assert r.status_code == 403
    assert (await get(api, "/me/earnings", s.a1)).status_code == 200


async def test_unknown_report_is_404_and_checked_before_params(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/nonexistent", s.director)
    assert r.status_code == 404
    r = await get(api, "/reports/nonexistent/export", s.director)
    assert r.status_code == 404


# ---------------- отчёт revenue ----------------


async def test_revenue_by_location_sums(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/revenue", s.director, **sep())
    assert r.status_code == 200, r.text
    rep = r.json()
    assert (
        rep["id"] == "revenue" and rep["date_from"] == "2026-09-01" and rep["location_id"] is None
    )
    assert [c["key"] for c in rep["columns"]][:2] == ["group", "orders_closed"]
    assert rep["truncated"] is False
    # по убыванию выручки: B (6000), затем A (5200)
    assert column(rep, "group") == ["B-Точка", "A-Точка"]
    a = by(rep, "group", "A-Точка")
    assert a["orders_closed"] == "2" and a["revenue"] == "5200.00"
    assert a["service_works"] == "3000.00" and a["detailing_works"] == "2000.00"
    assert a["parts"] == "500.00" and a["discounts"] == "300.00" and a["average_check"] == "2600.00"
    assert a["location_id"] == str(s.a.id)
    b = by(rep, "group", "B-Точка")
    assert b["revenue"] == "6000.00" and b["service_works"] == "5000.00" and b["parts"] == "1000.00"
    t = rep["totals"]
    assert (
        t["orders_closed"] == "3" and t["revenue"] == "11200.00" and t["average_check"] == "3733.33"
    )
    # тождество: выручка = сервис + детейлинг + запчасти - скидки
    for row in [a, b, t]:
        calc = (
            D(row["service_works"])
            + D(row["detailing_works"])
            + D(row["parts"])
            - D(row["discounts"])
        )
        assert calc == D(row["revenue"])
    assert rep["chart"]["x"] == "group"


async def test_revenue_by_day_uses_location_timezone(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/revenue", s.director, group_by="day", **sep())
    rep = r.json()
    assert len(rep["rows"]) == 30  # непрерывный ряд
    days = {row["group"]: row["revenue"] for row in rep["rows"]}
    assert days["2026-09-10"] == "3200.00"
    assert days["2026-09-11"] == "2000.00"  # 22:00 UTC = 01:00 МСК следующего дня
    assert days["2026-09-12"] == "6000.00"
    assert days["2026-09-01"] == "0.00"
    assert "2026-10-01" not in days  # заказ O6 (00:30 МСК 1 октября) вне периода


async def test_revenue_by_month_and_department_filter(api, db) -> None:
    s = await seed(db)
    r = await get(
        api,
        "/reports/revenue",
        s.director,
        group_by="month",
        date_from="2026-08-15",
        date_to="2026-10-15",
    )
    rep = r.json()
    months = {row["group"]: row for row in rep["rows"]}
    assert set(months) == {"2026-08", "2026-09", "2026-10"}
    assert months["2026-09"]["revenue"] == "11200.00"
    assert months["2026-10"]["revenue"] == "999.00"  # O6 по поясу МСК попал в октябрь
    assert months["2026-08"]["orders_closed"] == "0"


async def test_manager_sees_only_own_location(api, db) -> None:
    s = await seed(db)
    # отчёты директорские: менеджер получает 403 даже со своей точкой
    r = await get(api, "/reports/revenue", s.manager_a, location_id=str(s.a.id), **sep())
    assert r.status_code == 403
    # сводка точки — менеджеру только своя
    ok = await get(
        api,
        "/reports/location-summary",
        s.manager_a,
        location_id=str(s.a.id),
        period="custom",
        **sep(),
    )
    assert ok.status_code == 200 and ok.json()["revenue"] == "5200.00"
    other = await get(
        api,
        "/reports/location-summary",
        s.manager_a,
        location_id=str(s.b.id),
        period="custom",
        **sep(),
    )
    assert other.status_code == 404
    missing = await get(api, "/reports/location-summary", s.manager_a, period="custom", **sep())
    assert missing.status_code == 422 and "location_id" in missing.json()["error"]["fields"]


async def test_revenue_location_filter_and_validation(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/revenue", s.director, location_id=str(s.b.id), **sep())
    rep = r.json()
    assert rep["location_id"] == str(s.b.id)
    assert column(rep, "group") == ["B-Точка"] and rep["totals"]["revenue"] == "6000.00"
    assert (
        await get(api, "/reports/revenue", s.director, location_id=str(uuid.uuid4()), **sep())
    ).status_code == 404
    bad = await get(api, "/reports/revenue", s.director, group_by="category", **sep())
    assert bad.status_code == 422 and "group_by" in bad.json()["error"]["fields"]
    bad = await get(api, "/reports/revenue", s.director, department="mixed", **sep())
    assert bad.status_code == 422
    bad = await get(api, "/reports/revenue", s.director, date_from="не-дата")
    assert bad.status_code == 422


async def test_period_boundaries(api, db) -> None:
    s = await seed(db)
    ok = await get(
        api, "/reports/revenue", s.director, date_from="2026-01-01", date_to="2026-12-31"
    )
    assert ok.status_code == 200  # 365 дней
    ok = await get(
        api, "/reports/revenue", s.director, date_from="2024-01-01", date_to="2024-12-31"
    )
    assert ok.status_code == 200  # 366 дней (високосный год) — граница включительно
    too_long = await get(
        api, "/reports/revenue", s.director, date_from="2026-01-01", date_to="2027-01-02"
    )
    assert too_long.status_code == 422 and too_long.json()["error"]["fields"]["date_to"]
    inverted = await get(
        api, "/reports/revenue", s.director, date_from="2026-09-10", date_to="2026-09-09"
    )
    assert inverted.status_code == 422 and "date_to" in inverted.json()["error"]["fields"]
    one_day = await get(
        api, "/reports/revenue", s.director, date_from="2026-09-10", date_to="2026-09-10"
    )
    assert one_day.status_code == 200 and one_day.json()["totals"]["revenue"] == "3200.00"
    ancient = await get(
        api, "/reports/revenue", s.director, date_from="1900-01-01", date_to="1900-01-02"
    )
    assert ancient.status_code == 422
    dash = await get(
        api, "/reports/dashboard", s.director, date_from="2026-01-01", date_to="2027-01-02"
    )
    assert dash.status_code == 422


# ---------------- остальные отчёты ----------------


async def test_services_report(api, db) -> None:
    s = await seed(db)
    rep = (await get(api, "/reports/services", s.director, **sep())).json()
    assert column(rep, "name") == ["Прочие работы (вручную)", "Замена масла", "Полировка"]
    free, oil, polish = rep["rows"]
    assert free["revenue"] == "5000.00" and free["service_id"] is None and free["share"] == "50.00"
    assert oil["revenue"] == "3000.00" and oil["quantity"] == "3.00" and oil["orders"] == "2"
    assert oil["department"] == "Сервис" and oil["share"] == "30.00"
    assert polish["department"] == "Детейлинг" and polish["share"] == "20.00"
    assert rep["totals"]["revenue"] == "10000.00" and rep["totals"]["orders"] == "3"
    only = (await get(api, "/reports/services", s.director, department="detailing", **sep())).json()
    assert column(only, "name") == ["Полировка"]


async def test_mechanics_report(api, db) -> None:
    s = await seed(db)
    rep = (await get(api, "/reports/mechanics", s.director, **sep())).json()
    rows = {r["user_id"]: r for r in rep["rows"]}
    assert set(rows) == {str(s.a1.id), str(s.a2.id), str(s.mb.id)}
    a1 = rows[str(s.a1.id)]
    # i1 (1.5) + i3 (1 x 2 = 2.0); O4 не закрыт, O6 вне периода
    assert a1["items_done"] == "2" and a1["norm_hours"] == "3.50"
    assert a1["works_amount"] == "3000.00" and a1["net_amount"] == "2900.00"
    assert a1["actual_hours"] == "3.50"  # (90 + 120) / 60
    assert a1["efficiency"] == "100.00"
    assert rows[str(s.mb.id)]["works_amount"] == "5000.00"
    assert rep["totals"]["items_done"] == "4" and rep["totals"]["works_amount"] == "10000.00"
    detail = (
        await get(api, "/reports/mechanics", s.director, department="detailing", **sep())
    ).json()
    assert [r["user_id"] for r in detail["rows"]] == [str(s.a2.id)]


async def test_clients_report(api, db) -> None:
    s = await seed(db)
    rep = (await get(api, "/reports/clients", s.director, **sep())).json()
    assert [c["key"] for c in rep["columns"]][:3] == ["group", "new_clients", "repeat_clients"]
    t = rep["totals"]
    # единственный клиент: первый закрытый заказ O1 в периоде -> новый
    assert t["new_clients"] == "1" and t["repeat_clients"] == "0" and t["orders_closed"] == "3"
    monthly = (await get(api, "/reports/clients", s.director, group_by="month", **sep())).json()
    assert column(monthly, "group") == ["2026-09"]
    october = (
        await get(api, "/reports/clients", s.director, date_from="2026-10-01", date_to="2026-10-31")
    ).json()
    assert october["totals"]["new_clients"] == "0" and october["totals"]["repeat_clients"] == "1"


async def test_stock_report(api, db) -> None:
    s = await seed(db)
    rep = (await get(api, "/reports/stock", s.director, **sep())).json()
    p2 = by(rep, "sku", s.p2.sku)
    assert p2["sold_quantity"] == "2.000" and p2["revenue"] == "1000.00"
    assert p2["cost"] == "600.00" and p2["margin"] == "400.00" and p2["margin_percent"] == "40.00"
    assert p2["stock_value"] == "300.00"
    p1 = by(rep, "sku", s.p1.sku)
    assert p1["revenue"] == "500.00" and p1["cost"] == "300.00" and p1["margin"] == "200.00"
    assert p1["received_value"] == "3600.00" and p1["stock_value"] == "3000.00"
    t = rep["totals"]
    assert t["revenue"] == "1500.00" and t["cost"] == "900.00" and t["margin"] == "600.00"


async def test_expenses_report(api, db) -> None:
    s = await seed(db)
    rep = (await get(api, "/reports/expenses", s.director, **sep())).json()
    assert column(rep, "group") == ["Т-Аренда", "Т-Прочее"]  # отменённый расход не учитывается
    assert rep["rows"][0]["total"] == "3000.00" and rep["rows"][0]["count"] == "2"
    assert rep["rows"][1]["total"] == "500.00"
    assert rep["totals"]["total"] == "3500.00" and rep["totals"]["count"] == "3"
    loc = (await get(api, "/reports/expenses", s.director, group_by="location", **sep())).json()
    assert (
        by(loc, "group", "A-Точка")["total"] == "1500.00"
        and by(loc, "group", "B-Точка")["total"] == "2000.00"
    )
    month = (await get(api, "/reports/expenses", s.director, group_by="month", **sep())).json()
    assert column(month, "group") == ["2026-09"] and month["totals"]["total"] == "3500.00"


async def test_profit_report_and_month_alignment(api, db) -> None:
    s = await seed(db)
    db.add_all([
        PayrollScheme(user_id=s.a1.id, scheme_type="percent_of_works", percent=D(20),
                      valid_from=date(2026, 1, 1), created_by=s.director.id),
        PayrollScheme(user_id=s.a2.id, scheme_type="per_norm_hour", norm_hour_rate=D(500),
                      valid_from=date(2026, 1, 1), created_by=s.director.id),
        PayrollScheme(user_id=s.mb.id, scheme_type="fixed_plus_percent", percent=D(10),
                      fixed_monthly=D(30000), valid_from=date(2026, 1, 1),
                      created_by=s.director.id),
    ])  # fmt: skip
    await db.commit()
    r = await get(api, "/reports/profit", s.director, **sep())
    assert r.status_code == 200, r.text
    rep = r.json()
    a, b = by(rep, "group", "A-Точка"), by(rep, "group", "B-Точка")
    # A: 5200 - 300 (запчасти) - (580 + 1000) - 1500 (расходы)
    assert a["revenue"] == "5200.00" and a["parts_cost"] == "300.00"
    assert a["payroll"] == "1580.00" and a["expenses"] == "1500.00" and a["profit"] == "1820.00"
    assert a["margin_percent"] == "35.00"
    # B: 6000 - 600 - (500 + 30000) - 2000
    assert b["payroll"] == "30500.00" and b["profit"] == "-27100.00"
    assert rep["totals"]["revenue"] == "11200.00" and rep["totals"]["profit"] == "-25280.00"
    bad = await get(
        api, "/reports/profit", s.director, date_from="2026-09-02", date_to="2026-09-30"
    )
    assert bad.status_code == 422 and bad.json()["error"]["fields"] == {
        "date_from": "not_month_start"
    }
    bad = await get(
        api, "/reports/profit", s.director, date_from="2026-09-01", date_to="2026-09-29"
    )
    assert bad.status_code == 422 and bad.json()["error"]["fields"] == {"date_to": "not_month_end"}
    two = await get(
        api, "/reports/profit", s.director, date_from="2026-08-01", date_to="2026-09-30"
    )
    assert two.status_code == 200


# ---------------- дашборд ----------------


async def test_dashboard(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/dashboard", s.director, **sep())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["period"] == {
        "date_from": "2026-09-01", "date_to": "2026-09-30",
        "previous_from": "2026-08-02", "previous_to": "2026-08-31",
    }  # fmt: skip
    k = d["kpis"]
    assert k["revenue"]["value"] == "11200.00" and k["revenue"]["kind"] == "money"
    assert k["revenue"]["previous"] == "0.00" and k["revenue"]["delta"] is None
    assert k["cash_received"]["value"] == "9000.00"  # 3200 - 200 + 6000
    assert k["orders_closed"]["value"] == "3" and k["orders_closed"]["kind"] == "count"
    assert k["average_check"]["value"] == "3733.33"
    assert k["new_clients"]["value"] == "1" and k["repeat_clients"]["value"] == "0"
    # доля детейлинга = 2000 / 10000 работ
    assert k["detailing_share"]["value"] == "20.00" and k["detailing_share"]["kind"] == "percent"
    points = {p["date"]: p for p in d["revenue_series"]}
    assert len(points) == 30
    assert points["2026-09-11"]["total"] == "2000.00"
    assert points["2026-09-10"]["by_department"] == {
        "service_works": "1000.00", "detailing_works": "2000.00", "parts": "500.00",
    }  # fmt: skip
    assert {x["location"]["name"] for x in d["locations"]} == {"A-Точка", "B-Точка"}
    top = {t["name"]: t for t in d["top_services"]}
    assert top["Замена масла"]["revenue"] == "3000.00"
    assert d["attention"]["refunds"] == {"count": 1, "total": "200.00"}
    assert d["attention"]["low_stock"]["count"] == 1  # P2 в B: 1 < 5

    one = await get(api, "/reports/dashboard", s.director, location_id=str(s.a.id), **sep())
    assert one.json()["kpis"]["revenue"]["value"] == "5200.00" and one.json()["location_id"] == str(
        s.a.id
    )

    # сравнение с предыдущим периодом: октябрь 2026 против сентября
    prev = (
        await get(
            api, "/reports/dashboard", s.director, date_from="2026-10-01", date_to="2026-10-30"
        )
    ).json()
    rev = prev["kpis"]["revenue"]
    assert rev["value"] == "999.00" and rev["previous"] == "11200.00"
    assert D(rev["delta"]) == D("-91.08")


async def test_location_summary(api, db) -> None:
    s = await seed(db)
    r = await get(
        api,
        "/reports/location-summary",
        s.director,
        location_id=str(s.a.id),
        period="custom",
        **sep(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["revenue"] == "5200.00"
        and body["orders_closed"] == 2
        and body["average_check"] == "2600.00"
    )
    assert len(body["series"]) == 30
    mech = {m["user"]["id"]: m for m in body["mechanics"]}
    assert mech[str(s.a1.id)]["items_done"] == 2 and mech[str(s.a1.id)]["norm_hours"] == "3.50"
    assert mech[str(s.a1.id)]["works_amount"] == "3000.00"
    assert str(s.mb.id) not in mech
    for period in ("day", "week", "month"):
        ok = await get(
            api, "/reports/location-summary", s.manager_a, location_id=str(s.a.id), period=period
        )
        assert ok.status_code == 200, period
    bad = await get(
        api, "/reports/location-summary", s.director, location_id=str(s.a.id), period="year"
    )
    assert bad.status_code == 422
    bad = await get(
        api,
        "/reports/location-summary",
        s.mechanic if hasattr(s, "mechanic") else s.a1,
        location_id=str(s.a.id),
    )
    assert bad.status_code == 403


async def test_dashboard_today(api, db) -> None:
    s = await seed(db)
    tz = ZoneInfo(s.a.timezone)
    now = datetime.now(tz)
    order = WorkOrder(
        number=f"{s.a.code}-today", location_id=s.a.id, client_id=s.client.id,
        vehicle_id=s.vehicle.id,
        department="service", status="closed", manager_id=s.director.id, works_total=D(800),
        total=D(800), closed_at=datetime.now(UTC),
    )  # fmt: skip
    db.add(order)
    await db.flush()
    db.add(Payment(
        work_order_id=order.id, location_id=s.a.id, payment_type="payment", amount=D(800),
        method="card", paid_at=datetime.now(UTC), accepted_by=s.director.id,
    ))  # fmt: skip
    await db.commit()
    r = await get(api, "/dashboard/today", s.manager_a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["location"]["id"] == str(s.a.id) and body["date"] == now.date().isoformat()
    assert body["revenue_today"] == "800.00" and body["cash_received_today"] == "800.00"
    assert body["orders_closed_today"] == 1
    assert body["orders_open"] == 1  # O4 (готов, но не закрыт)
    assert body["ready_for_pickup"] == 1
    assert {m["user"]["id"] for m in body["mechanics"]} == {str(s.a1.id), str(s.a2.id)}
    assert (
        await get(api, "/dashboard/today", s.manager_a, location_id=str(s.b.id))
    ).status_code == 404
    assert (
        await get(api, "/dashboard/today", s.director, location_id=str(s.b.id))
    ).status_code == 200
    assert (await get(api, "/dashboard/today", s.a1)).status_code == 403


# ---------------- зарплата ----------------


async def scheme(
    api: httpx.AsyncClient, s: SimpleNamespace, user: User, **body: Any
) -> httpx.Response:
    payload = {"user_id": str(user.id), "valid_from": "2026-01-01", **body}
    return await api.post(f"{API}/payroll/schemes", json=payload, headers=token(s.director))


async def setup_schemes(api: httpx.AsyncClient, s: SimpleNamespace) -> None:
    for user, body in (
        (s.a1, {"scheme_type": "percent_of_works", "percent": "20.00"}),
        (s.a2, {"scheme_type": "per_norm_hour", "norm_hour_rate": "500.00"}),
        (s.mb, {"scheme_type": "fixed_plus_percent", "percent": "10", "fixed_monthly": "30000.00"}),
    ):
        r = await scheme(api, s, user, **body)
        assert r.status_code == 201, r.text


async def test_payroll_sheet_and_detail(api, db) -> None:
    s = await seed(db)
    await setup_schemes(api, s)
    adj = await api.post(
        f"{API}/payroll/adjustments",
        json={"user_id": str(s.a1.id), "month": "2026-09", "amount": "-100.00", "reason": "Штраф"},
        headers=token(s.director),
    )
    assert adj.status_code == 201, adj.text
    r = await get(api, "/payroll", s.director, month="2026-09")
    assert r.status_code == 200, r.text
    sheet = r.json()
    rows = {row["user"]["id"]: row for row in sheet["rows"]}
    a1 = rows[str(s.a1.id)]
    assert a1["items_done"] == 2 and a1["norm_hours"] == "3.50" and a1["base_amount"] == "2900.00"
    assert (
        a1["accrued"] == "580.00"
        and a1["adjustments_total"] == "-100.00"
        and a1["total"] == "480.00"
    )
    assert a1["scheme_summary"] == "20 % от работ" and a1["items_without_scheme"] == 0
    assert [loc["name"] for loc in a1["locations"]] == ["A-Точка"]
    a2 = rows[str(s.a2.id)]
    assert a2["accrued"] == "1000.00" and a2["scheme_summary"] == "500 ₽ за нормочас"
    mb = rows[str(s.mb.id)]
    assert mb["accrued"] == "30500.00" and mb["base_amount"] == "5000.00"
    t = sheet["totals"]
    assert (
        t["accrued"] == "32080.00"
        and t["adjustments_total"] == "-100.00"
        and t["total"] == "31980.00"
    )
    assert t["items_done"] == 4

    detail = (await get(api, f"/payroll/{s.a1.id}", s.director, month="2026-09")).json()
    assert detail["row"]["total"] == "480.00"
    lines = {line["item_id"]: line for line in detail["items"]}
    assert lines[str(s.i1.id)]["item_net"] == "900.00" and lines[str(s.i1.id)]["amount"] == "180.00"
    assert (
        lines[str(s.i3.id)]["norm_hours_total"] == "2.00"
        and lines[str(s.i3.id)]["amount"] == "400.00"
    )
    assert str(s.i5.id) not in lines and str(s.i6.id) not in lines  # не закрыт / другой месяц
    assert len(detail["adjustments"]) == 1 and detail["adjustments"][0]["month"] == "2026-09"
    assert detail["fixed"] == []
    fixed = (await get(api, f"/payroll/{s.mb.id}", s.director, month="2026-09")).json()
    assert fixed["fixed"][0]["days"] == 30 and fixed["fixed"][0]["amount"] == "30000.00"

    only_b = (
        await get(api, "/payroll", s.director, month="2026-09", location_id=str(s.b.id))
    ).json()
    assert str(s.a1.id) not in {row["user"]["id"] for row in only_b["rows"]}
    assert (await get(api, "/payroll", s.director, month="2026-13")).status_code == 422
    future = (date.today().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
    bad = await get(api, "/payroll", s.director, month=future)
    assert bad.status_code == 422 and "month" in bad.json()["error"]["fields"]
    assert (
        await get(api, f"/payroll/{uuid.uuid4()}", s.director, month="2026-09")
    ).status_code == 404


async def test_payroll_scheme_rules(api, db) -> None:
    s = await seed(db)
    r = await scheme(api, s, s.a1, scheme_type="percent_of_works", percent="20")
    assert r.status_code == 201
    created = r.json()
    assert created["is_current"] is True and created["valid_to"] is None
    assert created["description"] == "20 % от работ" and created["user"]["id"] == str(s.a1.id)
    first = date.today().replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    # закрытый месяц: задним числом схему добавлять нельзя
    closed = await scheme(
        api, s, s.a1, scheme_type="fixed", fixed_monthly="1000", valid_from="2026-06-01"
    )
    assert closed.status_code == 422 and closed.json()["error"]["fields"] == {
        "valid_from": "closed_month"
    }
    # схема отдела не пересекается с общей
    ok = await scheme(
        api, s, s.a1, scheme_type="percent_of_works", percent="30", department="detailing",
        valid_from=first.isoformat(),
    )  # fmt: skip
    assert ok.status_code == 201 and ok.json()["description"] == "30 % от работ (детейлинг)"
    # новая общая схема со следующего месяца закрывает предыдущую накануне
    follow = await scheme(
        api, s, s.a1, scheme_type="fixed", fixed_monthly="1000", valid_from=next_month.isoformat()
    )  # fmt: skip
    assert follow.status_code == 201, follow.text
    first_read = next(
        x for x in (await get(api, "/payroll/schemes", s.director, user_id=str(s.a1.id))).json()
        if x["id"] == created["id"]
    )  # fmt: skip
    assert first_read["valid_to"] == (next_month - timedelta(days=1)).isoformat()
    # пересечение: та же область (без отдела), тот же старт
    dup = await scheme(
        api, s, s.a1, scheme_type="fixed", fixed_monthly="2000", valid_from=next_month.isoformat()
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "scheme_overlap"
    # продление первой схемы на следующую -> пересечение (исключающее ограничение БД)
    stretch = await api.patch(
        f"{API}/payroll/schemes/{created['id']}",
        json={"valid_to": (next_month + timedelta(days=5)).isoformat()},
        headers=token(s.director),
    )
    assert stretch.status_code == 409 and stretch.json()["error"]["code"] == "scheme_overlap"
    # валидация набора полей по типу
    for body in (
        {"scheme_type": "percent_of_works"},
        {"scheme_type": "percent_of_works", "percent": "101"},
        {"scheme_type": "percent_of_works", "percent": "-1"},
        {"scheme_type": "per_norm_hour", "percent": "10"},
        {"scheme_type": "fixed", "fixed_monthly": "-5"},
        {"scheme_type": "fixed"},
        {"scheme_type": "unknown", "percent": "5"},
        {"scheme_type": "fixed", "fixed_monthly": "100", "extra": 1},
    ):
        bad = await scheme(api, s, s.a2, **body)
        assert bad.status_code == 422, body
    # неизвестный пользователь -> 404, неактивный не обрабатывается отдельно, менеджер -> 403
    ghost = await api.post(
        f"{API}/payroll/schemes",
        json={
            "user_id": str(uuid.uuid4()),
            "scheme_type": "fixed",
            "fixed_monthly": "1",
            "valid_from": "2026-01-01",
        },
        headers=token(s.director),
    )
    assert ghost.status_code == 404
    # закрытие схемы: PATCH valid_to
    mid = (first + timedelta(days=14)).isoformat()
    patched = await api.patch(
        f"{API}/payroll/schemes/{created['id']}", json={"valid_to": mid}, headers=token(s.director)
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["valid_to"] == mid
    early = await api.patch(
        f"{API}/payroll/schemes/{created['id']}",
        json={"valid_to": "2025-12-31"},
        headers=token(s.director),
    )
    assert early.status_code == 422 and early.json()["error"]["fields"] == {
        "valid_to": "before_valid_from"
    }
    past = await api.patch(
        f"{API}/payroll/schemes/{follow.json()['id']}",
        json={"valid_to": "2026-01-31"},
        headers=token(s.director),
    )
    assert past.status_code == 422 and "valid_to" in past.json()["error"]["fields"]
    listing = (await get(api, "/payroll/schemes", s.director, user_id=str(s.a1.id))).json()
    assert len(listing) == 3
    assert (await get(api, "/payroll/schemes", s.director, user_id=str(s.a2.id))).json() == []
    audit = (
        await db.scalars(select(AuditLog).where(AuditLog.entity_type == "payroll_scheme"))
    ).all()
    assert {a.action for a in audit} >= {"create", "update"}


async def test_payroll_scheme_delete_rules(api, db) -> None:
    s = await seed(db)
    past = await scheme(
        api, s, s.a1, scheme_type="fixed", fixed_monthly="1000", valid_from="2026-01-01"
    )
    delete = await api.delete(
        f"{API}/payroll/schemes/{past.json()['id']}", headers=token(s.director)
    )
    assert delete.status_code == 409 and delete.json()["error"]["code"] == "invalid_state"
    future_start = (date.today() + timedelta(days=60)).replace(day=1).isoformat()
    fut = await scheme(
        api, s, s.a2, scheme_type="fixed", fixed_monthly="1000", valid_from=future_start
    )
    assert fut.status_code == 201, fut.text
    ok = await api.delete(f"{API}/payroll/schemes/{fut.json()['id']}", headers=token(s.director))
    assert ok.status_code == 204
    gone = await api.delete(f"{API}/payroll/schemes/{fut.json()['id']}", headers=token(s.director))
    assert gone.status_code == 404


async def test_payroll_adjustments(api, db) -> None:
    s = await seed(db)

    async def post(**body: Any) -> httpx.Response:
        payload = {
            "user_id": str(s.a1.id),
            "month": "2026-09",
            "amount": "250.50",
            "reason": "Премия",
            **body,
        }
        return await api.post(f"{API}/payroll/adjustments", json=payload, headers=token(s.director))

    ok = await post()
    assert (
        ok.status_code == 201
        and ok.json()["amount"] == "250.50"
        and ok.json()["month"] == "2026-09"
    )
    assert ok.json()["created_by"]["id"] == str(s.director.id)
    zero = await post(amount="0.00")
    assert zero.status_code == 422 and "amount" in zero.json()["error"]["fields"]
    future = (date.today().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
    bad = await post(month=future)
    assert bad.status_code == 422 and "month" in bad.json()["error"]["fields"]
    for body in (
        {"month": "2026-9"},
        {"reason": ""},
        {"amount": "1.234"},
        {"amount": "abc"},
        {"extra": 1},
    ):
        assert (await post(**body)).status_code == 422, body
    assert (await post(user_id=str(uuid.uuid4()))).status_code == 404
    lst = (
        await get(api, "/payroll/adjustments", s.director, user_id=str(s.a1.id), month="2026-09")
    ).json()
    assert len(lst) == 1
    assert (await get(api, "/payroll/adjustments", s.director, month="2026-08")).json() == []
    # корректировки неизменяемы: нет PATCH/DELETE
    r = await api.delete(f"{API}/payroll/adjustments/{ok.json()['id']}", headers=token(s.director))
    assert r.status_code in (404, 405)


async def test_me_earnings_has_no_prices(api, db) -> None:
    s = await seed(db)
    await setup_schemes(api, s)
    r = await get(api, "/me/earnings", s.a1, month="2026-09")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accrued"] == "580.00" and body["items_done"] == 2 and body["norm_hours"] == "3.50"
    assert body["actual_hours"] == "3.50" and body["total"] == "580.00"
    # O4 закрыт? нет: работа i5 ждёт закрытия заказа
    assert body["awaiting_close"] == {"items_count": 1, "norm_hours": "1.00"}
    days = {d["date"]: d for d in body["days"]}
    assert set(days) == {"2026-09-10", "2026-09-11"}
    assert body["days"][0]["date"] == "2026-09-11"  # по убыванию
    text = r.text
    for forbidden in ("item_net", "unit_price", "scheme", "percent", "rate", "base_amount"):
        assert forbidden not in text, forbidden
    # чужой заработок получить нельзя: у механика свой месяц, чужая работа не попадает
    other = (await get(api, "/me/earnings", s.a2, month="2026-09")).json()
    assert other["accrued"] == "1000.00" and other["items_done"] == 1
    empty = (await get(api, "/me/earnings", s.a1, month="2025-01")).json()
    assert empty["accrued"] == "0.00" and empty["days"] == []
    future = (date.today().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
    assert (await get(api, "/me/earnings", s.a1, month=future)).status_code == 422


# ---------------- тепловая карта ----------------


async def seed_activity(db: AsyncSession, s: SimpleNamespace) -> None:
    # a1: 10.09 07:00-09:00 UTC (2 ч), 10.09 20:00 - 22:30 UTC пересекает полночь МСК (60 + 90 мин)
    db.add_all([
        WorkLog(item_id=s.i1.id, mechanic_id=s.a1.id,
                started_at=utc(2026, 9, 10, 7), ended_at=utc(2026, 9, 10, 9)),
        WorkLog(item_id=s.i3.id, mechanic_id=s.a1.id,
                started_at=utc(2026, 9, 10, 20), ended_at=utc(2026, 9, 10, 22, 30)),
        WorkLog(item_id=s.i1.id, mechanic_id=s.a1.id,
                started_at=utc(2026, 9, 12, 6), ended_at=utc(2026, 9, 12, 15)),
    ])  # fmt: skip

    def action(
        when: datetime,
        act: str = "update",
        etype: str = "work_order",
        entity: uuid.UUID | None = None,
    ):
        db.add(AuditLog(
            user_id=s.manager_a.id, action=act, entity_type=etype, entity_id=entity or s.o1.id,
            location_id=s.a.id, created_at=when,
        ))  # fmt: skip

    action(utc(2026, 9, 10, 9))
    action(utc(2026, 9, 10, 10))
    action(utc(2026, 9, 10, 11), act="login")  # не считается
    action(utc(2026, 9, 11, 6), etype="client", entity=s.client.id)
    action(utc(2026, 9, 11, 22, 30))  # 01:30 МСК 12.09
    await db.commit()


async def test_heatmap_hours(api, db) -> None:
    s = await seed(db)
    await seed_activity(db, s)
    r = await get(
        api,
        f"/users/{s.a1.id}/activity-heatmap",
        s.director,
        **{"from": "2026-09-08", "to": "2026-09-14"},
    )
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["kind"] == "hours" and h["from"] == "2026-09-08" and h["to"] == "2026-09-14"
    assert h["timezone"] == "Europe/Moscow" and h["thresholds"] == [2, 5, 8]
    days = {d["date"]: d for d in h["days"]}
    assert len(days) == 7
    d10 = days["2026-09-10"]
    assert (
        d10["minutes"] == 180
        and d10["hours"] == "3.00"
        and d10["level"] == 2
        and d10["actions"] is None
    )
    assert d10["works_count"] == 2 and len(d10["order_numbers"]) == 2
    d11 = days["2026-09-11"]  # хвост интервала после полуночи МСК
    assert d11["minutes"] == 90 and d11["level"] == 1
    d12 = days["2026-09-12"]
    assert d12["minutes"] == 540 and d12["level"] == 4  # 9 ч > 8
    assert days["2026-09-08"]["level"] == 0 and days["2026-09-08"]["minutes"] == 0
    sm = h["summary"]
    assert (
        sm["working_days"] == 3 and sm["total_hours"] == "13.50" and sm["longest_streak_days"] == 3
    )
    assert sm["average_per_working_day"] == "4.50" and sm["total_actions"] is None
    assert h["user"]["id"] == str(s.a1.id)

    details = (
        await get(
            api,
            f"/users/{s.a1.id}/activity-details",
            s.director,
            date_from="2026-09-10",
            date_to="2026-09-12",
        )
    ).json()
    assert details["kind"] == "hours"
    assert [d["date"] for d in details["days"]] == [
        "2026-09-12",
        "2026-09-11",
        "2026-09-10",
    ]  # по убыванию
    day10 = details["days"][2]
    assert (
        day10["total_minutes"] == 180 and day10["actions"] is None and day10["truncated"] is False
    )
    assert sorted(e["minutes"] for e in day10["entries"]) == [60, 120]
    assert day10["entries"][0]["plate_number"] == "А001АА77"
    assert details["days"][1]["entries"][0]["minutes"] == 90


async def test_heatmap_actions_and_levels(api, db) -> None:
    s = await seed(db)
    await seed_activity(db, s)
    r = await get(
        api,
        f"/users/{s.manager_a.id}/activity-heatmap",
        s.director,
        **{"from": "2026-09-09", "to": "2026-09-13"},
    )
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["kind"] == "actions" and h["thresholds"] == [5, 15, 30]
    days = {d["date"]: d for d in h["days"]}
    assert (
        days["2026-09-10"]["actions"] == 2 and days["2026-09-10"]["level"] == 1
    )  # login не считается
    assert days["2026-09-10"]["hours"] is None and days["2026-09-10"]["minutes"] is None
    assert days["2026-09-10"]["works_count"] == 1 and len(days["2026-09-10"]["order_numbers"]) == 1
    assert days["2026-09-11"]["actions"] == 1 and days["2026-09-11"]["works_count"] == 0
    assert days["2026-09-12"]["actions"] == 1  # 22:30 UTC = 01:30 МСК следующего дня
    sm = h["summary"]
    assert sm["total_actions"] == 4 and sm["working_days"] == 3 and sm["longest_streak_days"] == 3
    assert sm["average_per_working_day"] == "1.3" and sm["total_hours"] is None
    details = (
        await get(
            api,
            f"/users/{s.manager_a.id}/activity-details",
            s.director,
            date_from="2026-09-10",
            date_to="2026-09-10",
        )
    ).json()
    assert details["kind"] == "actions"
    entries = details["days"][0]["entries"]
    assert len(entries) == 2 and details["days"][0]["actions"] == 2
    assert entries[0]["entity_type"] == "work_order" and entries[0]["order_number"] == s.o1.number
    assert s.o1.number in entries[0]["label"]
    assert "login" not in {e["action"] for e in entries}


async def test_heatmap_rights(api, db) -> None:
    s = await seed(db)
    # директор — любой пользователь
    for target in (s.a1, s.manager_a, s.director):
        r = await get(api, f"/users/{target.id}/activity-heatmap", s.director)
        assert r.status_code == 200, target.role
    # менеджер — механики своих точек; чужие, себя, директора и менеджеров — 404
    assert (await get(api, f"/users/{s.a1.id}/activity-heatmap", s.manager_a)).status_code == 200
    for target in (s.mb, s.manager_a, s.manager_b, s.director):
        r = await get(api, f"/users/{target.id}/activity-heatmap", s.manager_a)
        assert r.status_code == 404, target.role
    # механик — только свои данные
    assert (await get(api, f"/users/{s.a1.id}/activity-heatmap", s.a1)).status_code == 200
    assert (await get(api, f"/users/{s.a2.id}/activity-heatmap", s.a1)).status_code == 404
    assert (await get(api, f"/users/{s.manager_a.id}/activity-details", s.a1)).status_code == 404
    assert (
        await get(api, f"/users/{uuid.uuid4()}/activity-heatmap", s.director)
    ).status_code == 404
    assert (
        await get(api, f"/users/{uuid.uuid4()}/activity-details", s.manager_a)
    ).status_code == 404
    assert (await api.get(f"{API}/users/{s.a1.id}/activity-heatmap")).status_code == 401


async def test_heatmap_validation_and_defaults(api, db) -> None:
    s = await seed(db)
    r = await get(api, f"/users/{s.a1.id}/activity-heatmap", s.director)
    assert r.status_code == 200
    h = r.json()
    today = datetime.now(MSK).date()
    assert h["to"] == today.isoformat() and h["from"] == (today - timedelta(days=364)).isoformat()
    assert len(h["days"]) == 365
    ok = await get(
        api,
        f"/users/{s.a1.id}/activity-heatmap",
        s.director,
        **{"from": "2025-09-10", "to": "2026-09-10"},
    )
    assert ok.status_code == 200 and len(ok.json()["days"]) == 366  # граница включительно
    long = await get(
        api,
        f"/users/{s.a1.id}/activity-heatmap",
        s.director,
        **{"from": "2025-09-09", "to": "2026-09-10"},
    )
    assert long.status_code == 422 and "to" in long.json()["error"]["fields"]
    inv = await get(
        api,
        f"/users/{s.a1.id}/activity-heatmap",
        s.director,
        **{"from": "2026-09-10", "to": "2026-09-09"},
    )
    assert inv.status_code == 422 and "to" in inv.json()["error"]["fields"]
    future_to = (today + timedelta(days=10)).isoformat()
    cut = await get(
        api,
        f"/users/{s.a1.id}/activity-heatmap",
        s.director,
        **{"from": today.isoformat(), "to": future_to},
    )
    assert cut.status_code == 200 and [d["date"] for d in cut.json()["days"]] == [today.isoformat()]
    wide = await get(
        api,
        f"/users/{s.a1.id}/activity-details",
        s.director,
        date_from="2026-09-01",
        date_to="2026-10-02",
    )
    assert wide.status_code == 422 and "date_to" in wide.json()["error"]["fields"]
    edge = await get(
        api,
        f"/users/{s.a1.id}/activity-details",
        s.director,
        date_from="2026-09-01",
        date_to="2026-10-01",
    )
    assert edge.status_code == 200  # ровно 31 день
    default = (await get(api, f"/users/{s.a1.id}/activity-details", s.director)).json()
    assert default["days"] == []
    assert (
        await get(api, f"/users/{s.a1.id}/activity-heatmap", s.director, **{"from": "не-дата"})
    ).status_code == 422


async def test_heatmap_open_interval_counts_until_now(api, db) -> None:
    s = await seed(db)
    started = datetime.now(UTC) - timedelta(minutes=30)
    db.add(WorkLog(item_id=s.i1.id, mechanic_id=s.a1.id, started_at=started, ended_at=None))
    await db.commit()
    today = datetime.now(MSK).date()
    # Интервал может пересечь местную полночь (прогон в 00:00–00:30 МСК): суммируем все его дни.
    first = started.astimezone(MSK).date()
    h = (
        await get(
            api,
            f"/users/{s.a1.id}/activity-heatmap",
            s.director,
            **{"from": first.isoformat(), "to": today.isoformat()},
        )
    ).json()
    total = sum(d["minutes"] or 0 for d in h["days"])
    assert 25 <= total <= 45  # 30 минут (с запасом на округление)  # noqa: PLR2004


# ---------------- экспорт ----------------


async def test_export_csv_and_audit(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/revenue/export", s.director, format="csv", **sep())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="report-revenue-2026-09-01_2026-09-30.csv"'
    )
    assert r.headers["cache-control"] == "no-store"
    assert r.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][0] == "Точка" and rows[0][-1] == "Средний чек"
    by_name = {row[0]: row for row in rows[1:]}
    assert by_name["B-Точка"][6] == "6000,00"  # запятая как десятичный разделитель
    assert by_name["Итого"][6] == "11200,00"
    audit = (await db.scalars(select(AuditLog).where(AuditLog.action == "export"))).all()
    assert (
        len(audit) == 1 and audit[0].entity_type == "report" and audit[0].user_id == s.director.id
    )
    assert audit[0].changes["report_id"] == "revenue" and audit[0].changes["format"] == "csv"


async def test_export_xlsx(api, db) -> None:
    s = await seed(db)
    r = await get(api, "/reports/revenue/export", s.director, **sep())  # xlsx по умолчанию
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.headers["content-disposition"].endswith('.xlsx"')
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = set(z.namelist())
        assert {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"} <= names
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "B-Точка" in sheet and "6000" in sheet
    bad = await get(api, "/reports/revenue/export", s.director, format="pdf", **sep())
    assert bad.status_code == 422


async def test_export_payroll(api, db) -> None:
    s = await seed(db)
    await setup_schemes(api, s)
    r = await get(api, "/payroll/export", s.director, month="2026-09", format="csv")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="payroll-2026-09.csv"'
    text = r.content.decode("utf-8-sig")
    assert "580,00" in text and "30500,00" in text
    x = await get(api, "/payroll/export", s.director, month="2026-09")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    audit = (
        await db.scalars(
            select(AuditLog).where(AuditLog.entity_type == "payroll", AuditLog.action == "export")
        )
    ).all()
    assert len(audit) == 2


async def test_export_rate_limit(api, db) -> None:
    s = await seed(db)
    for i in range(10):
        r = await get(api, "/reports/expenses/export", s.director, format="csv", **sep())
        assert r.status_code == 200, i
    r = await get(api, "/reports/expenses/export", s.director, format="csv", **sep())
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    # лимит на пользователя: другой директор не затронут
    other = await make_user(db, Role.director)
    ok = await get(api, "/reports/expenses/export", other, format="csv", **sep())
    assert ok.status_code == 200


def test_safe_text_neutralizes_formulas() -> None:
    for danger in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=x", "\r=x"):
        assert safe_text(danger).startswith("'"), danger
    assert safe_text("Обычный текст") == "Обычный текст"
    assert safe_text(None) == ""


async def test_export_neutralizes_formula_in_data(api, db) -> None:
    s = await seed(db)
    s.rent.name = '=HYPERLINK("http://evil")'
    await db.commit()
    r = await get(api, "/reports/expenses/export", s.director, format="csv", **sep())
    text = r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and ";=HYPERLINK" not in text and not text.startswith("=")
    x = await get(api, "/reports/expenses/export", s.director, **sep())
    with zipfile.ZipFile(io.BytesIO(x.content)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert ">=HYPERLINK" not in sheet


# ---------------- ежедневная сводка ----------------


async def test_daily_summary_run_once(db, monkeypatch) -> None:
    s = await seed(db)
    published: list[dict] = []

    async def fake_publish(session, event_type, payload, **kw):
        published.append({"type": event_type, "payload": payload, **kw})

    async def fake_setting(session, key):
        assert key == "daily_summary_time"
        return setting["value"]

    setting = {"value": "21:00"}
    monkeypatch.setattr(daily_summary.events, "publish", fake_publish)
    monkeypatch.setattr(daily_summary, "get_setting", fake_setting)
    monkeypatch.setattr(daily_summary.SummaryState, "last_date", None)
    app_tz = daily_summary.app_tz()
    day = datetime(2026, 9, 10, tzinfo=app_tz)

    assert await daily_summary.run_once(db, now=day.replace(hour=20, minute=59)) is False  # рано
    assert published == []
    assert await daily_summary.run_once(db, now=day.replace(hour=21, minute=0)) is True
    assert len(published) == 1
    ev = published[0]
    assert ev["type"] == "report.daily_summary" and ev["location_id"] is None
    assert ev["dedup_key"] == "report.daily_summary:2026-09-10"
    assert ev["payload"]["date"] == "2026-09-10" and ev["payload"]["location_name"] is None
    assert set(ev["payload"]) >= {
        "revenue",
        "orders_closed",
        "orders_open",
        "cash_received",
        "breakdown",
    }
    assert "A-Точка" in ev["payload"]["breakdown"] and "B-Точка" in ev["payload"]["breakdown"]
    # повторный вызов в тот же день ничего не публикует
    assert await daily_summary.run_once(db, now=day.replace(hour=22)) is False
    assert len(published) == 1
    # следующий день — снова
    assert (
        await daily_summary.run_once(db, now=(day + timedelta(days=1)).replace(hour=21, minute=5))
        is True
    )
    assert len(published) == 2
    # null отключает сводку
    setting["value"] = None
    assert await daily_summary.run_once(db, now=(day + timedelta(days=2)).replace(hour=23)) is False
    setting["value"] = "мусор"
    assert await daily_summary.run_once(db, now=(day + timedelta(days=2)).replace(hour=23)) is False
    assert s.o4 is not None


def test_daily_summary_helpers() -> None:
    from datetime import time

    assert daily_summary.parse_summary_time("21:00") == time(21, 0)
    assert daily_summary.parse_summary_time("07:05") == time(7, 5)
    for bad in (None, "", "24:00", "9:00", "21:60", 2100):
        assert daily_summary.parse_summary_time(bad) is None
    assert [daily_summary.orders_word(n) for n in (0, 1, 2, 5, 11, 12, 21, 22, 25, 111)] == [
        "заказов", "заказ", "заказа", "заказов", "заказов",
        "заказов", "заказ", "заказа", "заказов", "заказов",
    ]  # fmt: skip


async def test_daily_summary_task_is_registered() -> None:
    import app.tasks.daily_summary  # noqa: F401
    from app.core import periodic

    assert "daily_summary" in periodic.REGISTRY
    assert periodic.REGISTRY["daily_summary"].interval == 60
