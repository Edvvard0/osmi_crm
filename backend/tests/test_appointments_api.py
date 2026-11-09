"""Модуль 4: запись (календарь): права, валидация, пересечения, гонки, часовые пояса, Location."""

# ruff: noqa: E501

import asyncio
import uuid
from datetime import time
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import create_access_token
from app.models import (
    AuditLog,
    Client,
    Location,
    Role,
    Service,
    ServiceCategory,
    User,
    UserLocation,
    Vehicle,
    WorkPost,
)
from app.models.appointment import Appointment, AppointmentService
from app.services import appointments as svc
from tests.conftest import build_app
from tests.factories import bearer, make_location, make_user
from tests.security.payloads import ALL

API = "/api/v1"
APPT = f"{API}/appointments"

pytestmark = pytest.mark.integration

# ---------------- данные ----------------


def token(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


def at(h: int, m: int = 0, day: int = 10, off: str = "+03:00", month: int = 11) -> str:
    return f"2026-{month:02d}-{day:02d}T{h:02d}:{m:02d}:00{off}"


async def seed(db: AsyncSession, *, unique: bool = False) -> SimpleNamespace:
    """Точки А (Москва) и Б (Владивосток), роли, посты, клиент с авто, услуги."""
    sfx = uuid.uuid4().hex[:8]
    a = await make_location(db, f"Точка А {sfx}", timezone="Europe/Moscow")
    b = await make_location(db, f"Точка Б {sfx}", timezone="Asia/Vladivostok")
    manager = await make_user(db, Role.manager, locations=[a])
    manager_b = await make_user(db, Role.manager, locations=[b])
    director = await make_user(db, Role.director)
    mechanic = await make_user(db, Role.mechanic, locations=[a])

    def post(loc: Location, name: str, dept: str = "service", active: bool = True) -> WorkPost:
        return WorkPost(
            location_id=loc.id,
            name=name,
            post_type="lift" if dept == "service" else "detailing_box",
            department=dept,
            is_active=active,
        )

    p1, p2 = post(a, "Подъёмник 1"), post(a, "Подъёмник 2")
    p_det = post(a, "Бокс", "detailing")
    p_off = post(a, "Закрытый", active=False)
    p_b = post(b, "Подъёмник Б")
    p_b2 = post(b, "Подъёмник Б2")

    def person(name: str, archived: bool = False) -> Client:
        phone = "+79" + str(uuid.uuid4().int)[:9]
        return Client(
            client_type="person",
            full_name=name,
            phone=phone,
            archived_at=func.now() if archived else None,
        )

    client, other, archived_client = (
        person("Иван Петров"),
        person("Пётр Сидоров"),
        person("Архив", True),
    )
    db.add_all([p1, p2, p_det, p_off, p_b, p_b2, client, other, archived_client])
    await db.flush()

    def car(owner: Client, archived: bool = False, plate: str | None = "А123ВС77") -> Vehicle:
        return Vehicle(
            client_id=owner.id,
            make="Kia",
            model="Rio",
            plate_number=plate,
            archived_at=func.now() if archived else None,
        )

    vehicle, other_vehicle = car(client), car(other, plate=None)
    archived_vehicle, archived_owner_vehicle = car(client, True), car(archived_client)
    cat_s = ServiceCategory(name=f"ТО {sfx}", department="service")
    cat_d = ServiceCategory(name=f"Полировка {sfx}", department="detailing")
    db.add_all([vehicle, other_vehicle, archived_vehicle, archived_owner_vehicle, cat_s, cat_d])
    await db.flush()

    def service(cat: ServiceCategory, name: str, active: bool = True) -> Service:
        return Service(
            category_id=cat.id,
            code="S" + uuid.uuid4().hex[:12],
            name=name,
            department=cat.department,
            unit="pcs",
            base_price=Decimal(100),
            duration_minutes=30,
            is_active=active,
        )

    s1, s2 = service(cat_s, "Замена масла"), service(cat_s, "Диагностика")
    s_det, s_off = service(cat_d, "Полировка кузова"), service(cat_s, "Снятая", active=False)
    db.add_all([s1, s2, s_det, s_off])
    await db.commit()
    return SimpleNamespace(
        a=a, b=b, p1=p1, p2=p2, p_det=p_det, p_off=p_off, p_b=p_b, p_b2=p_b2,
        client=client, other=other, archived_client=archived_client,
        vehicle=vehicle, other_vehicle=other_vehicle, archived_vehicle=archived_vehicle,
        archived_owner_vehicle=archived_owner_vehicle,
        s1=s1, s2=s2, s_det=s_det, s_off=s_off, cats=[cat_s, cat_d],
        users=[manager, manager_b, director, mechanic],
        m=token(manager), mb=token(manager_b), d=token(director), x=token(mechanic),
    )  # fmt: skip


@pytest.fixture
async def ctx(api, db):
    return await seed(db)


def body(c: SimpleNamespace, **kw: object) -> dict[str, object]:
    base = {
        "location_id": str(c.a.id),
        "client_id": str(c.client.id),
        "vehicle_id": str(c.vehicle.id),
        "post_id": str(c.p1.id),
        "department": "service",
        "start_at": at(10),
        "end_at": at(11),
    }
    return {**base, **kw}


async def create(api, c, h=None, **kw) -> httpx.Response:
    return await api.post(APPT, headers=h or c.m, json=body(c, **kw))


async def ok(api, c, h=None, **kw) -> dict:
    r = await create(api, c, h, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def err(r: httpx.Response) -> dict:
    return r.json()["error"]


async def audit(db, action=None):
    q = select(AuditLog).where(AuditLog.entity_type == "appointment")
    if action:
        q = q.where(AuditLog.action == action)
    return list(await db.scalars(q.order_by(AuditLog.id)))


async def count(db) -> int:
    return await db.scalar(select(func.count()).select_from(Appointment)) or 0


# ---------------- права ----------------


async def test_unauthenticated_is_401(api):
    for method, url in [("GET", APPT), ("POST", APPT), ("PATCH", f"{APPT}/{uuid.uuid4()}")]:
        r = await api.request(method, url, json={})
        assert r.status_code == 401


async def test_mechanic_is_403_everywhere(api, ctx):
    one = f"{APPT}/{uuid.uuid4()}"
    q = f"?location_id={ctx.a.id}&date_from=2026-11-10&date_to=2026-11-10"
    for method, url, payload in [
        ("GET", APPT + q, None),
        ("POST", APPT, body(ctx)),
        ("GET", one, None),
        ("PATCH", one, {}),
        ("POST", f"{one}/status", {"status": "confirmed"}),
    ]:
        r = await api.request(method, url, headers=ctx.x, json=payload)
        assert r.status_code == 403 and err(r)["code"] == "forbidden", (method, url)


async def test_manager_other_location_is_404(api, ctx):
    created = await ok(api, ctx)
    one = f"{APPT}/{created['id']}"
    q = f"?location_id={ctx.a.id}&date_from=2026-11-10&date_to=2026-11-10"
    assert (await api.get(APPT + q, headers=ctx.mb)).status_code == 404
    assert (await api.post(APPT, headers=ctx.mb, json=body(ctx))).status_code == 404
    assert (await api.get(one, headers=ctx.mb)).status_code == 404
    assert (await api.patch(one, headers=ctx.mb, json={"comment": "x"})).status_code == 404
    r = await api.post(f"{one}/status", headers=ctx.mb, json={"status": "confirmed"})
    assert r.status_code == 404
    # запись не изменилась
    assert (await api.get(one, headers=ctx.m)).json()["status"] == "scheduled"


async def test_unknown_ids_are_404(api, ctx):
    ghost = str(uuid.uuid4())
    r = await api.post(APPT, headers=ctx.d, json=body(ctx, location_id=ghost))
    assert r.status_code == 404
    assert (await api.get(f"{APPT}/{ghost}", headers=ctx.d)).status_code == 404
    assert (await api.patch(f"{APPT}/{ghost}", headers=ctx.d, json={})).status_code == 404
    r = await api.post(f"{APPT}/{ghost}/status", headers=ctx.d, json={"status": "confirmed"})
    assert r.status_code == 404
    assert (await api.get(f"{APPT}/not-a-uuid", headers=ctx.d)).status_code == 422


async def test_director_works_on_any_location(api, ctx):
    created = await ok(api, ctx, ctx.d)
    ours = await ok(
        api, ctx, ctx.d, location_id=str(ctx.b.id), post_id=str(ctx.p_b.id), start_at=at(10, off="+10:00"),
        end_at=at(11, off="+10:00"),
    )  # fmt: skip
    assert created["location_id"] == str(ctx.a.id) and ours["location_id"] == str(ctx.b.id)
    r = await api.get(f"{APPT}/{ours['id']}", headers=ctx.d)
    assert r.status_code == 200
    r = await api.post(f"{APPT}/{ours['id']}/status", headers=ctx.d, json={"status": "confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"


async def test_manager_in_two_locations_sees_only_own(api, db, ctx):
    # менеджер точки Б не видит записи точки А даже при прямом запросе списка по id записи
    created = await ok(api, ctx)
    r = await api.get(
        f"{APPT}?location_id={ctx.b.id}&date_from=2026-11-10&date_to=2026-11-10", headers=ctx.mb
    )
    assert r.status_code == 200 and r.json() == []
    assert (await api.get(f"{APPT}/{created['id']}", headers=ctx.mb)).status_code == 404


# ---------------- создание: форма ответа ----------------


async def test_create_contract_shape_and_audit(api, db, ctx):
    r = await create(
        api, ctx, service_ids=[str(ctx.s2.id), str(ctx.s1.id)], comment="  Стук в подвеске  "
    )
    assert r.status_code == 201, r.text
    a = r.json()
    # work_order_number — расширение модуля 5 (api-contract-m5.md)
    assert set(a) == {
        "id", "location_id", "client_id", "vehicle_id", "post_id", "department", "start_at",
        "end_at", "status", "comment", "service_ids", "services", "client", "vehicle",
        "work_order_id", "work_order_number", "created_by", "created_at", "updated_at",
    }  # fmt: skip
    assert a["status"] == "scheduled" and a["work_order_id"] is None
    assert a["work_order_number"] is None
    assert (
        a["start_at"] == "2026-11-10T10:00:00+03:00" and a["end_at"] == "2026-11-10T11:00:00+03:00"
    )
    assert a["created_at"].endswith("+03:00") and a["updated_at"].endswith("+03:00")
    assert a["comment"] == "Стук в подвеске"
    assert a["services"] == [
        {"id": str(ctx.s2.id), "name": "Диагностика"},
        {"id": str(ctx.s1.id), "name": "Замена масла"},
    ]
    assert a["service_ids"] == [str(ctx.s2.id), str(ctx.s1.id)]
    assert a["client"] == {
        "id": str(ctx.client.id), "full_name": "Иван Петров", "phone": ctx.client.phone,
    }  # fmt: skip
    assert a["vehicle"] == {
        "id": str(ctx.vehicle.id), "make": "Kia", "model": "Rio", "plate_number": "А123ВС77",
    }  # fmt: skip
    assert a["created_by"] == str(ctx.users[0].id)
    rows = await audit(db, "create")
    assert len(rows) == 1 and rows[0].entity_id == uuid.UUID(a["id"])
    assert rows[0].location_id == ctx.a.id and rows[0].user_id == ctx.users[0].id
    assert rows[0].changes["status"] == {"old": None, "new": "scheduled"}
    assert r.headers.get("x-request-id")


async def test_get_one_matches_create_and_list(api, ctx):
    a = await ok(api, ctx, service_ids=[str(ctx.s1.id)])
    r = await api.get(f"{APPT}/{a['id']}", headers=ctx.m)
    assert r.status_code == 200 and r.json() == a
    r = await api.get(
        f"{APPT}?location_id={ctx.a.id}&date_from=2026-11-10&date_to=2026-11-10", headers=ctx.m
    )
    assert r.json() == [a]


async def test_optional_fields_default(api, ctx):
    r = await api.post(
        APPT,
        headers=ctx.m,
        json={k: v for k, v in body(ctx).items() if k != "post_id"},
    )
    assert r.status_code == 201
    a = r.json()
    assert a["post_id"] is None and a["comment"] is None and a["service_ids"] == []
    assert a["services"] == []
    a = await ok(api, ctx, start_at=at(12), end_at=at(13), comment="   ", service_ids=[])
    assert a["comment"] is None


async def test_plate_less_vehicle_is_ok(api, ctx):
    a = await ok(api, ctx, client_id=str(ctx.other.id), vehicle_id=str(ctx.other_vehicle.id))
    assert a["vehicle"]["plate_number"] is None


async def test_service_ids_deduplicated(api, ctx):
    a = await ok(api, ctx, service_ids=[str(ctx.s1.id)] * 3)
    assert a["service_ids"] == [str(ctx.s1.id)]


async def test_detailing_department(api, ctx):
    a = await ok(
        api, ctx, department="detailing", post_id=str(ctx.p_det.id), service_ids=[str(ctx.s_det.id)]
    )
    assert a["department"] == "detailing" and a["services"][0]["name"] == "Полировка кузова"


# ---------------- создание: валидация ----------------

FIELD_CASES = [
    ("vehicle_of_other_client", lambda c: {"vehicle_id": str(c.other_vehicle.id)}, "vehicle_id"),
    ("vehicle_unknown", lambda c: {"vehicle_id": str(uuid.uuid4())}, "vehicle_id"),
    ("client_unknown", lambda c: {"client_id": str(uuid.uuid4())}, "vehicle_id"),
    ("vehicle_archived", lambda c: {"vehicle_id": str(c.archived_vehicle.id)}, "vehicle_id"),
    (
        "client_archived",
        lambda c: {
            "client_id": str(c.archived_client.id),
            "vehicle_id": str(c.archived_owner_vehicle.id),
        },
        "vehicle_id",
    ),
    ("post_other_location", lambda c: {"post_id": str(c.p_b.id)}, "post_id"),
    ("post_inactive", lambda c: {"post_id": str(c.p_off.id)}, "post_id"),
    ("post_unknown", lambda c: {"post_id": str(uuid.uuid4())}, "post_id"),
    ("post_wrong_department", lambda c: {"post_id": str(c.p_det.id)}, "post_id"),
    ("department_vs_post", lambda c: {"department": "detailing"}, "post_id"),
    ("service_inactive", lambda c: {"service_ids": [str(c.s_off.id)]}, "service_ids"),
    ("service_other_dept", lambda c: {"service_ids": [str(c.s_det.id)]}, "service_ids"),
    ("service_unknown", lambda c: {"service_ids": [str(uuid.uuid4())]}, "service_ids"),
    (
        "service_one_bad_of_two",
        lambda c: {"service_ids": [str(c.s1.id), str(c.s_det.id)]},
        "service_ids",
    ),
    ("start_not_multiple_of_5", lambda c: {"start_at": at(10, 3)}, "start_at"),
    ("end_not_multiple_of_5", lambda c: {"end_at": at(11, 7)}, "end_at"),
    ("start_seconds", lambda c: {"start_at": "2026-11-10T10:00:30+03:00"}, "start_at"),
    ("start_micro", lambda c: {"start_at": "2026-11-10T10:00:00.5+03:00"}, "start_at"),
    ("duration_10_min", lambda c: {"end_at": at(10, 10)}, "end_at"),
    ("duration_zero", lambda c: {"end_at": at(10)}, "end_at"),
    ("end_before_start", lambda c: {"end_at": at(9)}, "end_at"),
    ("duration_over_12h", lambda c: {"start_at": at(9), "end_at": at(21, 5)}, "end_at"),
    ("year_too_early", lambda c: {"start_at": "0001-01-01T10:00:00+03:00"}, "start_at"),
    ("year_too_late", lambda c: {"end_at": "9999-01-01T10:00:00+03:00"}, "end_at"),
]


@pytest.mark.parametrize(("name", "make", "field"), FIELD_CASES, ids=[x[0] for x in FIELD_CASES])
async def test_create_field_errors(api, db, ctx, name, make, field):
    before = await count(db)
    r = await create(api, ctx, **make(ctx))
    assert r.status_code == 422, r.text
    assert err(r)["code"] == "validation_error" and field in err(r)["fields"], r.text
    assert await count(db) == before


async def test_create_reports_all_failing_fields(api, ctx):
    r = await create(
        api, ctx, vehicle_id=str(uuid.uuid4()), post_id=str(ctx.p_off.id), start_at=at(10, 1)
    )
    assert set(err(r)["fields"]) == {"vehicle_id", "post_id", "start_at"}


@pytest.mark.parametrize(
    "bad",
    [
        {"start_at": "2026-11-10T10:00:00"},  # без пояса
        {"end_at": "2026-11-10T11:00:00"},
        {"start_at": "не дата"},
        {"start_at": None},
        {"start_at": 12345},
        {"department": "wash"},
        {"department": None},
        {"location_id": "nope"},
        {"client_id": None},
        {"vehicle_id": 5},
        {"post_id": "x"},
        {"service_ids": "abc"},
        {"service_ids": ["x"]},
        {"service_ids": [None]},
        {"service_ids": [str(uuid.uuid4())] * 51},
        {"comment": "x" * 1001},
        {"comment": 5},
        {"status": "confirmed"},  # статус задаётся сервером
        {"id": str(uuid.uuid4())},
        {"created_by": str(uuid.uuid4())},
        {"work_order_id": str(uuid.uuid4())},
        {"extra": 1},
    ],
)
async def test_create_schema_rejects(api, db, ctx, bad):
    before = await count(db)
    r = await create(api, ctx, **bad)
    assert r.status_code == 422 and err(r)["code"] == "validation_error", r.text
    assert await count(db) == before


@pytest.mark.parametrize(
    "missing", ["location_id", "client_id", "vehicle_id", "department", "start_at", "end_at"]
)
async def test_create_required_fields(api, ctx, missing):
    payload = {k: v for k, v in body(ctx).items() if k != missing}
    r = await api.post(APPT, headers=ctx.m, json=payload)
    assert r.status_code == 422 and missing in err(r)["fields"]


async def test_create_not_json_object(api, ctx):
    for payload in ([], "x", 5):
        r = await api.post(APPT, headers=ctx.m, json=payload)
        assert r.status_code == 422


async def test_duration_boundaries(api, ctx):
    await ok(api, ctx, start_at=at(10), end_at=at(10, 15))  # ровно 15 минут
    await ok(api, ctx, post_id=str(ctx.p2.id), start_at=at(9), end_at=at(21))  # ровно 12 часов
    r = await create(api, ctx, post_id=str(ctx.p2.id), start_at=at(10), end_at=at(10, 14))
    assert r.status_code == 422


# ---------------- рабочие часы ----------------


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (at(8, 45), at(9, 45)),  # начало до открытия
        (at(20, 30), at(21, 5)),  # конец после закрытия
        (at(21), at(21, 30)),  # целиком после закрытия
        (at(23, 30), at(23, 55)),
        (at(23), at(1, day=11)),  # переход через полночь
        (at(6), at(8)),
    ],
)
async def test_outside_working_hours(api, db, ctx, start, end):
    before = await count(db)
    r = await create(api, ctx, start_at=start, end_at=end)
    assert r.status_code == 422, r.text
    assert err(r)["code"] == "outside_working_hours" and err(r)["fields"] == {}
    assert await count(db) == before


@pytest.mark.parametrize(
    ("start", "end"), [(at(9), at(10)), (at(20), at(21)), (at(9), at(21)), (at(9), at(9, 15))]
)
async def test_working_hours_boundaries_are_inclusive(api, ctx, start, end):
    await ok(api, ctx, start_at=start, end_at=end)


async def test_working_hours_follow_location_settings(api, ctx):
    r = await api.patch(
        f"{API}/locations/{ctx.a.id}",
        headers=ctx.d,
        json={"work_start": "07:00", "work_end": "22:00"},
    )
    assert r.status_code == 200
    await ok(api, ctx, start_at=at(7), end_at=at(8))
    r = await create(api, ctx, post_id=str(ctx.p2.id), start_at=at(21, 30), end_at=at(22, 30))
    assert err(r)["code"] == "outside_working_hours"


async def test_midnight_crossing_with_round_the_clock_location(api, db):
    loc = await make_location(db, work_start=time(0), work_end=time(23, 59))
    mgr = await make_user(db, Role.manager, locations=[loc])
    c = await seed(db)
    h = token(mgr)
    post = WorkPost(location_id=loc.id, name="П", post_type="lift", department="service")
    db.add(post)
    await db.commit()
    kw = {"location_id": str(loc.id), "post_id": str(post.id)}
    # сутки не пересекаются: 23:00–23:45 допустимо, 23:30–00:15 следующего дня — нет
    r = await api.post(APPT, headers=h, json=body(c, **kw, start_at=at(23), end_at=at(23, 45)))
    assert r.status_code == 201, r.text
    r = await api.post(
        APPT, headers=h, json=body(c, **kw, start_at=at(23, 30), end_at=at(0, 15, day=11))
    )
    assert err(r)["code"] == "outside_working_hours"


# ---------------- пересечения ----------------


async def test_back_to_back_is_allowed(api, ctx):
    await ok(api, ctx, start_at=at(10), end_at=at(11))
    await ok(api, ctx, start_at=at(11), end_at=at(12))  # конец одной = начало другой
    await ok(api, ctx, start_at=at(9), end_at=at(10))  # и с другой стороны
    await ok(api, ctx, start_at=at(12), end_at=at(12, 15))


OVERLAPS = [
    ("same", at(10), at(11)),
    ("starts_inside", at(10, 30), at(11, 30)),
    ("ends_inside", at(9, 30), at(10, 30)),
    ("contains", at(9, 30), at(11, 30)),
    ("contained", at(10, 15), at(10, 45)),
    ("one_slot_overlap", at(10, 45), at(11, 15)),
    ("last_slot", at(10, 45), at(11)),
]


@pytest.mark.parametrize(("name", "start", "end"), OVERLAPS, ids=[x[0] for x in OVERLAPS])
async def test_overlap_is_409_with_details(api, db, ctx, name, start, end):
    first = await ok(api, ctx)
    before, audits = await count(db), len(await audit(db, "create"))
    r = await create(api, ctx, start_at=start, end_at=end)
    assert r.status_code == 409, r.text
    e = err(r)
    assert e["code"] == "post_busy"
    assert e["details"] == {
        "conflict_id": first["id"],
        "start_at": "2026-11-10T10:00:00+03:00",
        "end_at": "2026-11-10T11:00:00+03:00",
    }
    # откат полностью: ни записи, ни услуг, ни аудита
    assert await count(db) == before and len(await audit(db, "create")) == audits


async def test_overlap_rolls_back_services(api, db, ctx):
    await ok(api, ctx)
    r = await create(api, ctx, service_ids=[str(ctx.s1.id)])
    assert r.status_code == 409
    assert await db.scalar(select(func.count()).select_from(AppointmentService)) == 0


async def test_same_time_other_post_is_ok(api, ctx):
    await ok(api, ctx)
    await ok(api, ctx, post_id=str(ctx.p2.id))


async def test_same_post_other_day_is_ok(api, ctx):
    await ok(api, ctx)
    await ok(api, ctx, start_at=at(10, day=11), end_at=at(11, day=11))


async def test_no_post_has_no_overlap_check(api, ctx):
    a = await ok(api, ctx, post_id=None)
    b = await ok(api, ctx, post_id=None)
    assert a["post_id"] is None and a["id"] != b["id"]
    await ok(api, ctx)  # запись на пост не конфликтует с записями без поста


async def test_post_busy_reports_first_conflict_in_point_timezone(api, ctx):
    off = "+10:00"
    kw = {"location_id": str(ctx.b.id), "post_id": str(ctx.p_b.id)}
    first = await ok(api, ctx, ctx.mb, **kw, start_at=at(10, off=off), end_at=at(11, off=off))
    r = await create(api, ctx, ctx.mb, **kw, start_at=at(10, 30, off=off), end_at=at(12, off=off))
    assert err(r)["details"] == {
        "conflict_id": first["id"],
        "start_at": "2026-11-10T10:00:00+10:00",
        "end_at": "2026-11-10T11:00:00+10:00",
    }


@pytest.mark.parametrize("status", ["cancelled", "no_show"])
async def test_final_statuses_free_the_slot(api, ctx, status):
    first = await ok(api, ctx)
    assert (await create(api, ctx)).status_code == 409
    r = await api.post(f"{APPT}/{first['id']}/status", headers=ctx.m, json={"status": status})
    assert r.status_code == 200
    second = await ok(api, ctx)  # слот свободен
    assert (await create(api, ctx)).status_code == 409  # и снова занят новой записью
    assert second["id"] != first["id"]


@pytest.mark.parametrize("status", ["scheduled", "confirmed", "arrived"])
async def test_occupying_statuses_block_the_slot(api, ctx, status):
    first = await ok(api, ctx)
    if status != "scheduled":
        r = await api.post(f"{APPT}/{first['id']}/status", headers=ctx.m, json={"status": status})
        assert r.status_code == 200
    r = await create(api, ctx)
    assert r.status_code == 409 and err(r)["details"]["conflict_id"] == first["id"]


# ---------------- список ----------------


async def test_list_requires_params_and_validates(api, ctx):
    base = f"location_id={ctx.a.id}&date_from=2026-11-10&date_to=2026-11-10"
    for drop in ("location_id", "date_from", "date_to"):
        q = "&".join(p for p in base.split("&") if not p.startswith(drop))
        r = await api.get(f"{APPT}?{q}", headers=ctx.m)
        assert r.status_code == 422 and drop in err(r)["fields"]
    for extra in [
        "date_from=2026-13-40",
        "date_from=abc",
        "status=bogus",
        "department=wash",
        "post_id=x",
        "client_id=x",
    ]:
        r = await api.get(f"{APPT}?{base}&{extra}", headers=ctx.m)
        assert r.status_code == 422, extra


async def test_list_range_limits(api, ctx):
    def q(f: str, t: str) -> str:
        return f"{APPT}?location_id={ctx.a.id}&date_from={f}&date_to={t}"

    assert (
        await api.get(q("2026-11-01", "2026-12-01"), headers=ctx.m)
    ).status_code == 200  # 31 день
    r = await api.get(q("2026-11-01", "2026-12-02"), headers=ctx.m)  # 32 дня
    assert r.status_code == 422 and "date_to" in err(r)["fields"]
    r = await api.get(q("2026-11-10", "2026-11-09"), headers=ctx.m)
    assert r.status_code == 422 and "date_to" in err(r)["fields"]
    assert (await api.get(q("1999-01-01", "1999-01-02"), headers=ctx.m)).status_code == 422
    assert (await api.get(q("2100-12-30", "2100-12-31"), headers=ctx.m)).status_code == 200
    assert (await api.get(q("2100-12-31", "2101-01-01"), headers=ctx.m)).status_code == 422


async def test_list_order_and_filters(api, db, ctx):
    late = await ok(api, ctx, start_at=at(15), end_at=at(16))
    early = await ok(api, ctx, post_id=str(ctx.p2.id), start_at=at(9), end_at=at(10))
    mid = await ok(
        api, ctx, post_id=str(ctx.p_det.id), department="detailing", start_at=at(12), end_at=at(13),
        client_id=str(ctx.other.id), vehicle_id=str(ctx.other_vehicle.id),
    )  # fmt: skip
    nxt = await ok(api, ctx, start_at=at(10, day=11), end_at=at(11, day=11))
    await api.post(f"{APPT}/{late['id']}/status", headers=ctx.m, json={"status": "cancelled"})

    def q(**kw: str) -> str:
        p = {"location_id": str(ctx.a.id), "date_from": "2026-11-10", "date_to": "2026-11-10", **kw}
        return APPT + "?" + "&".join(f"{k}={v}" for k, v in p.items())

    async def ids(**kw: str) -> list[str]:
        r = await api.get(q(**kw), headers=ctx.m)
        assert r.status_code == 200, r.text
        return [a["id"] for a in r.json()]

    assert await ids() == [early["id"], mid["id"], late["id"]]  # по возрастанию start_at
    assert await ids(date_to="2026-11-11") == [early["id"], mid["id"], late["id"], nxt["id"]]
    assert await ids(date_from="2026-11-11", date_to="2026-11-11") == [nxt["id"]]
    assert await ids(date_from="2026-11-09", date_to="2026-11-09") == []
    assert await ids(post_id=str(ctx.p2.id)) == [early["id"]]
    assert await ids(department="detailing") == [mid["id"]]
    assert await ids(status="cancelled") == [late["id"]]
    assert await ids(status="scheduled") == [early["id"], mid["id"]]
    assert await ids(client_id=str(ctx.other.id)) == [mid["id"]]
    assert await ids(department="service", status="cancelled") == [late["id"]]


async def test_list_has_no_other_location_rows(api, ctx):
    await ok(api, ctx)
    await ok(
        api, ctx, ctx.mb, location_id=str(ctx.b.id), post_id=str(ctx.p_b.id), start_at=at(10, off="+10:00"),
        end_at=at(11, off="+10:00"),
    )  # fmt: skip
    r = await api.get(
        f"{APPT}?location_id={ctx.a.id}&date_from=2026-11-10&date_to=2026-11-11", headers=ctx.d
    )
    assert [a["location_id"] for a in r.json()] == [str(ctx.a.id)]


# ---------------- часовые пояса ----------------


async def test_utc_input_is_returned_in_point_timezone(api, ctx):
    # 07:00Z = 10:00 в Москве
    a = await ok(api, ctx, start_at="2026-11-10T07:00:00Z", end_at="2026-11-10T08:00:00Z")
    assert (
        a["start_at"] == "2026-11-10T10:00:00+03:00" and a["end_at"] == "2026-11-10T11:00:00+03:00"
    )
    # то же мгновение в другом смещении
    r = await create(api, ctx, start_at=at(15, off="+08:00"), end_at=at(16, off="+08:00"))
    assert r.status_code == 409 and err(r)["details"]["conflict_id"] == a["id"]


async def test_vladivostok_point_uses_its_own_hours_and_offset(api, ctx):
    kw = {"location_id": str(ctx.b.id), "post_id": str(ctx.p_b.id)}
    a = await ok(api, ctx, ctx.mb, **kw, start_at=at(9, off="+10:00"), end_at=at(10, off="+10:00"))
    assert a["start_at"] == "2026-11-10T09:00:00+10:00" and a["created_at"].endswith("+10:00")
    # 08:30 по Владивостоку — до открытия, хотя в Москве это 01:30 предыдущих/текущих суток
    r = await create(
        api, ctx, ctx.mb, **kw, start_at=at(8, 30, off="+10:00"), end_at=at(9, 30, off="+10:00")
    )
    assert err(r)["code"] == "outside_working_hours"
    # 10:00+03:00 = 17:00 во Владивостоке — внутри рабочих часов
    kw2 = {**kw, "post_id": str(ctx.p_b2.id)}
    b = await ok(api, ctx, ctx.mb, **kw2, start_at=at(10), end_at=at(11))
    assert b["start_at"] == "2026-11-10T17:00:00+10:00"


async def test_day_boundaries_follow_point_timezone(api, db):
    moscow = await make_location(
        db, timezone="Europe/Moscow", work_start=time(0), work_end=time(23, 59)
    )
    vlad = await make_location(
        db, timezone="Asia/Vladivostok", work_start=time(0), work_end=time(23, 59)
    )
    mgr = await make_user(db, Role.manager, locations=[moscow, vlad])
    c = await seed(db)
    h = token(mgr)

    async def post_for(loc, off, hh, mm, day):
        p = WorkPost(
            location_id=loc.id,
            name=f"П{uuid.uuid4().hex[:6]}",
            post_type="lift",
            department="service",
        )
        db.add(p)
        await db.commit()
        r = await api.post(
            APPT,
            headers=h,
            json=body(
                c, location_id=str(loc.id), post_id=str(p.id),
                start_at=at(hh, mm, day=day, off=off), end_at=at(hh + 1, mm, day=day, off=off),
            ),
        )  # fmt: skip
        assert r.status_code == 201, r.text
        return r.json()

    async def ids(loc, f, t):
        r = await api.get(f"{APPT}?location_id={loc.id}&date_from={f}&date_to={t}", headers=h)
        assert r.status_code == 200, r.text
        return [a["id"] for a in r.json()]

    # Москва: 00:15 11 ноября по местному = 21:15Z 10 ноября, но дата в поясе точки — 11-е
    m = await post_for(moscow, "+03:00", 0, 15, 11)
    assert await ids(moscow, "2026-11-10", "2026-11-10") == []
    assert await ids(moscow, "2026-11-11", "2026-11-11") == [m["id"]]
    # Владивосток: 09:00 11 ноября = 23:00Z 10 ноября
    v = await post_for(vlad, "+10:00", 9, 0, 11)
    assert await ids(vlad, "2026-11-10", "2026-11-10") == []
    assert await ids(vlad, "2026-11-11", "2026-11-11") == [v["id"]]
    # конец суток
    late = await post_for(moscow, "+03:00", 22, 30, 10)
    assert await ids(moscow, "2026-11-10", "2026-11-10") == [late["id"]]


async def test_dst_offsets_in_list(api, db):
    loc = await make_location(db, timezone="Europe/Berlin")
    mgr = await make_user(db, Role.manager, locations=[loc])
    c = await seed(db)
    p = WorkPost(location_id=loc.id, name="П", post_type="lift", department="service")
    db.add(p)
    await db.commit()
    h = token(mgr)
    kw = {"location_id": str(loc.id), "post_id": str(p.id)}
    # 28 марта — зима (+01:00), 29 марта — переход на лето (+02:00)
    for day, off in ((28, "+01:00"), (29, "+02:00")):
        r = await api.post(
            APPT,
            headers=h,
            json=body(c, **kw, start_at=at(10, day=day, month=3, off=off), end_at=at(11, day=day, month=3, off=off)),
        )  # fmt: skip
        assert r.status_code == 201, r.text
    r = await api.get(
        f"{APPT}?location_id={loc.id}&date_from=2026-03-28&date_to=2026-03-29", headers=h
    )
    assert [a["start_at"] for a in r.json()] == [
        "2026-03-28T10:00:00+01:00",
        "2026-03-29T10:00:00+02:00",
    ]


# ---------------- статусы ----------------

ALL_STATUSES = ["scheduled", "confirmed", "arrived", "no_show", "cancelled"]
ALLOWED = {
    "scheduled": {"confirmed", "arrived", "no_show", "cancelled"},
    "confirmed": {"arrived", "no_show", "cancelled"},
}


@pytest.mark.parametrize("start_from", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
async def test_status_transition_matrix(api, db, ctx, start_from, target):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}/status"
    if start_from != "scheduled":
        # путь в нужный исходный статус
        via = {
            "confirmed": ["confirmed"],
            "arrived": ["arrived"],
            "no_show": ["no_show"],
            "cancelled": ["cancelled"],
        }
        for step in via[start_from]:
            assert (await api.post(url, headers=ctx.m, json={"status": step})).status_code == 200
    r = await api.post(url, headers=ctx.m, json={"status": target})
    if target in ALLOWED.get(start_from, set()):
        assert r.status_code == 200, r.text
        assert r.json()["status"] == target
        row = (await audit(db, "status"))[-1]
        assert row.changes == {"status": {"old": start_from, "new": target}}
    else:
        assert r.status_code == 409 and err(r)["code"] == "invalid_transition"
        assert (await api.get(f"{APPT}/{a['id']}", headers=ctx.m)).json()["status"] == start_from


async def test_confirmed_to_confirmed_and_chain(api, ctx):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}/status"
    assert (await api.post(url, headers=ctx.m, json={"status": "confirmed"})).status_code == 200
    r = await api.post(url, headers=ctx.m, json={"status": "scheduled"})  # назад нельзя
    assert err(r)["code"] == "invalid_transition"
    r = await api.post(url, headers=ctx.m, json={"status": "arrived"})
    assert r.status_code == 200 and r.json()["updated_at"] >= a["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"status": "bogus"}, {"status": None}, {"status": 1}, {"status": "arrived", "x": 1}, []],
)
async def test_status_payload_validation(api, ctx, payload):
    a = await ok(api, ctx)
    r = await api.post(f"{APPT}/{a['id']}/status", headers=ctx.m, json=payload)
    assert r.status_code == 422


# ---------------- изменение (PATCH) ----------------


async def test_patch_move_and_resize(api, db, ctx):
    a = await ok(api, ctx, service_ids=[str(ctx.s1.id)], comment="было")
    url = f"{APPT}/{a['id']}"
    r = await api.patch(
        url, headers=ctx.m,
        json={"post_id": str(ctx.p2.id), "start_at": at(14), "end_at": at(15, 30), "comment": "стало"},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["post_id"] == str(ctx.p2.id) and b["comment"] == "стало"
    assert (
        b["start_at"] == "2026-11-10T14:00:00+03:00" and b["end_at"] == "2026-11-10T15:30:00+03:00"
    )
    assert b["service_ids"] == a["service_ids"] and b["status"] == "scheduled"
    assert b["updated_at"] >= a["updated_at"] and b["created_at"] == a["created_at"]
    rows = await audit(db, "update")
    assert len(rows) == 1 and set(rows[0].changes) == {"post_id", "start_at", "end_at", "comment"}
    # старый слот свободен, новый занят
    await ok(api, ctx)
    assert (
        await create(api, ctx, post_id=str(ctx.p2.id), start_at=at(14, 30), end_at=at(15))
    ).status_code == 409


async def test_patch_resize_over_own_old_slot_is_allowed(api, ctx):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}"
    for s, e in [(at(10), at(12)), (at(9, 30), at(12)), (at(10, 30), at(11)), (at(10), at(11))]:
        r = await api.patch(url, headers=ctx.m, json={"start_at": s, "end_at": e})
        assert r.status_code == 200, r.text


async def test_patch_into_busy_slot_is_409_and_nothing_changes(api, db, ctx):
    a = await ok(api, ctx)
    other = await ok(api, ctx, start_at=at(12), end_at=at(13))
    r = await api.patch(
        f"{APPT}/{other['id']}", headers=ctx.m, json={"start_at": at(10, 30), "end_at": at(11, 30)}
    )
    assert r.status_code == 409 and err(r)["code"] == "post_busy"
    assert err(r)["details"]["conflict_id"] == a["id"]
    assert (await api.get(f"{APPT}/{other['id']}", headers=ctx.m)).json() == other
    # перенос на занятый другой пост
    r = await api.patch(
        f"{APPT}/{other['id']}",
        headers=ctx.m,
        json={"post_id": str(ctx.p1.id), "start_at": at(10), "end_at": at(11)},
    )
    assert r.status_code == 409
    assert (
        await db.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "update")
        )
        == 0
    )


async def test_patch_only_post_conflict(api, ctx):
    await ok(api, ctx)
    other = await ok(api, ctx, post_id=str(ctx.p2.id))
    r = await api.patch(f"{APPT}/{other['id']}", headers=ctx.m, json={"post_id": str(ctx.p1.id)})
    assert r.status_code == 409


async def test_patch_unassign_and_assign_post(api, ctx):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}"
    r = await api.patch(url, headers=ctx.m, json={"post_id": None})
    assert r.status_code == 200 and r.json()["post_id"] is None
    free = await ok(api, ctx)  # пост освободился
    assert (
        await api.patch(url, headers=ctx.m, json={"post_id": str(ctx.p1.id)})
    ).status_code == 409
    assert free["post_id"] == str(ctx.p1.id)
    r = await api.patch(url, headers=ctx.m, json={"post_id": str(ctx.p2.id)})
    assert r.status_code == 200 and r.json()["post_id"] == str(ctx.p2.id)


async def test_patch_comment_and_services(api, db, ctx):
    a = await ok(api, ctx, comment="c", service_ids=[str(ctx.s1.id)])
    url = f"{APPT}/{a['id']}"
    r = await api.patch(url, headers=ctx.m, json={"comment": None})
    assert r.json()["comment"] is None and r.json()["service_ids"] == [str(ctx.s1.id)]
    r = await api.patch(url, headers=ctx.m, json={"comment": "   "})
    assert r.json()["comment"] is None
    r = await api.patch(url, headers=ctx.m, json={"service_ids": [str(ctx.s2.id)]})
    assert [s["name"] for s in r.json()["services"]] == ["Диагностика"]
    r = await api.patch(
        url, headers=ctx.m, json={"service_ids": [str(ctx.s2.id), str(ctx.s1.id), str(ctx.s2.id)]}
    )
    assert [s["name"] for s in r.json()["services"]] == ["Диагностика", "Замена масла"]
    r = await api.patch(url, headers=ctx.m, json={"service_ids": []})
    assert r.json()["services"] == [] and r.json()["service_ids"] == []
    rows = await audit(db, "update")
    assert any("service_ids" in x.changes for x in rows)


async def test_patch_same_values_writes_no_audit(api, db, ctx):
    a = await ok(api, ctx, comment="c", service_ids=[str(ctx.s1.id)])
    url = f"{APPT}/{a['id']}"
    for payload in [
        {},
        {"comment": "c"},
        {"service_ids": [str(ctx.s1.id)]},
        {"start_at": at(10), "end_at": at(11)},
        {"department": "service", "post_id": str(ctx.p1.id)},
    ]:
        r = await api.patch(url, headers=ctx.m, json=payload)
        assert r.status_code == 200 and r.json()["service_ids"] == [str(ctx.s1.id)]
    assert await audit(db, "update") == []


async def test_patch_department_rules(api, ctx):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}"
    r = await api.patch(url, headers=ctx.m, json={"department": "detailing"})  # пост — сервисный
    assert r.status_code == 422 and "post_id" in err(r)["fields"]
    r = await api.patch(
        url, headers=ctx.m, json={"department": "detailing", "post_id": str(ctx.p_det.id)}
    )
    assert r.status_code == 200 and r.json()["department"] == "detailing"
    # услуги прежнего отдела при смене отдела не проходят
    b = await ok(api, ctx, start_at=at(14), end_at=at(15), service_ids=[str(ctx.s1.id)])
    r = await api.patch(
        f"{APPT}/{b['id']}", headers=ctx.m, json={"department": "detailing", "post_id": None}
    )
    assert r.status_code == 422 and "service_ids" in err(r)["fields"]
    r = await api.patch(
        f"{APPT}/{b['id']}", headers=ctx.m,
        json={"department": "detailing", "post_id": None, "service_ids": [str(ctx.s_det.id)]},
    )  # fmt: skip
    assert r.status_code == 200 and r.json()["services"][0]["name"] == "Полировка кузова"


@pytest.mark.parametrize(
    ("name", "make", "field"),
    [
        ("post_other_location", lambda c: {"post_id": str(c.p_b.id)}, "post_id"),
        ("post_inactive", lambda c: {"post_id": str(c.p_off.id)}, "post_id"),
        ("post_unknown", lambda c: {"post_id": str(uuid.uuid4())}, "post_id"),
        ("post_wrong_dept", lambda c: {"post_id": str(c.p_det.id)}, "post_id"),
        ("service_inactive", lambda c: {"service_ids": [str(c.s_off.id)]}, "service_ids"),
        ("service_other_dept", lambda c: {"service_ids": [str(c.s_det.id)]}, "service_ids"),
        ("only_start", lambda c: {"start_at": at(12)}, "end_at"),
        ("only_end", lambda c: {"end_at": at(12)}, "start_at"),
        ("start_step", lambda c: {"start_at": at(12, 1), "end_at": at(13)}, "start_at"),
        ("end_step", lambda c: {"start_at": at(12), "end_at": at(13, 2)}, "end_at"),
        ("too_short", lambda c: {"start_at": at(12), "end_at": at(12, 10)}, "end_at"),
        ("too_long", lambda c: {"start_at": at(9), "end_at": at(21, 5)}, "end_at"),
        ("reversed", lambda c: {"start_at": at(13), "end_at": at(12)}, "end_at"),
    ],
)
async def test_patch_field_errors(api, ctx, name, make, field):
    a = await ok(api, ctx)
    r = await api.patch(f"{APPT}/{a['id']}", headers=ctx.m, json=make(ctx))
    assert r.status_code == 422, r.text
    assert field in err(r)["fields"]
    assert (await api.get(f"{APPT}/{a['id']}", headers=ctx.m)).json() == a


async def test_patch_outside_working_hours(api, ctx):
    a = await ok(api, ctx)
    for s, e in [(at(8), at(9, 30)), (at(20, 30), at(21, 30)), (at(23), at(1, day=11))]:
        r = await api.patch(f"{APPT}/{a['id']}", headers=ctx.m, json={"start_at": s, "end_at": e})
        assert r.status_code == 422 and err(r)["code"] == "outside_working_hours"


async def test_patch_unrelated_field_ignores_changed_working_hours(api, ctx):
    a = await ok(api, ctx)
    r = await api.patch(f"{API}/locations/{ctx.a.id}", headers=ctx.d, json={"work_start": "12:00"})
    assert r.status_code == 200
    r = await api.patch(f"{APPT}/{a['id']}", headers=ctx.m, json={"comment": "новое"})
    assert r.status_code == 200  # старое время не пересматривается, пока его не меняют
    r = await api.patch(
        f"{APPT}/{a['id']}", headers=ctx.m, json={"start_at": at(10, 30), "end_at": at(11)}
    )
    assert err(r)["code"] == "outside_working_hours"


@pytest.mark.parametrize(
    "bad",
    [
        {"start_at": None},
        {"end_at": None},
        {"department": None},
        {"service_ids": None},
        {"start_at": "2026-11-10T10:00:00", "end_at": at(11)},
        {"department": "wash"},
        {"status": "cancelled"},
        {"client_id": str(uuid.uuid4())},
        {"vehicle_id": str(uuid.uuid4())},
        {"location_id": str(uuid.uuid4())},
        {"work_order_id": str(uuid.uuid4())},
        {"comment": "x" * 1001},
        {"extra": 1},
    ],
)
async def test_patch_schema_rejects(api, ctx, bad):
    a = await ok(api, ctx)
    r = await api.patch(f"{APPT}/{a['id']}", headers=ctx.m, json=bad)
    assert r.status_code == 422 and err(r)["code"] == "validation_error", r.text
    assert (await api.get(f"{APPT}/{a['id']}", headers=ctx.m)).json() == a


@pytest.mark.parametrize("final", ["arrived", "no_show", "cancelled"])
async def test_patch_in_final_status_is_409_invalid_state(api, db, ctx, final):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}"
    assert (
        await api.post(f"{url}/status", headers=ctx.m, json={"status": final})
    ).status_code == 200
    for payload in [
        {"comment": "x"},
        {"start_at": at(12), "end_at": at(13)},
        {"post_id": None},
        {},
    ]:
        r = await api.patch(url, headers=ctx.m, json=payload)
        assert r.status_code == 409 and err(r)["code"] == "invalid_state", payload
    assert await audit(db, "update") == []


async def test_patch_confirmed_is_allowed(api, ctx):
    a = await ok(api, ctx)
    url = f"{APPT}/{a['id']}"
    await api.post(f"{url}/status", headers=ctx.m, json={"status": "confirmed"})
    r = await api.patch(url, headers=ctx.m, json={"comment": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"


async def test_patch_move_to_freed_slot_after_cancel(api, ctx):
    first = await ok(api, ctx)
    moving = await ok(api, ctx, start_at=at(12), end_at=at(13))
    target = {"start_at": at(10, 30), "end_at": at(11, 30)}
    assert (
        await api.patch(f"{APPT}/{moving['id']}", headers=ctx.m, json=target)
    ).status_code == 409
    await api.post(f"{APPT}/{first['id']}/status", headers=ctx.m, json={"status": "cancelled"})
    assert (
        await api.patch(f"{APPT}/{moving['id']}", headers=ctx.m, json=target)
    ).status_code == 200


# ---------------- текстовые поля ----------------


async def test_comment_injections_create_and_patch(api, db, ctx):
    a = await ok(api, ctx, start_at=at(9), end_at=at(9, 30))
    for n, payload in enumerate(ALL, 1):
        start = at(10 + n // 4 % 9, (n % 4) * 15)
        r = await create(
            api,
            ctx,
            post_id=None,
            start_at=start,
            end_at=at(10 + n // 4 % 9, (n % 4) * 15 + 15),
            comment=payload,
        )
        assert r.status_code in (201, 422), (payload[:30], r.text[:200])
        if r.status_code == 201:
            c = r.json()["comment"]
            assert c is None or ("<" not in c and ">" not in c and "\x00" not in c)
            assert len(c or "") <= 1000
        r = await api.patch(f"{APPT}/{a['id']}", headers=ctx.m, json={"comment": payload})
        assert r.status_code in (200, 422)
        assert r.status_code != 500
    # таблица цела
    assert await count(db) >= 1


async def test_sql_like_comment_is_stored_verbatim(api, ctx):
    text = "'; DROP TABLE appointments;-- ' OR '1'='1"
    a = await ok(api, ctx, comment=text)
    assert a["comment"] == text
    assert (await api.get(f"{APPT}/{a['id']}", headers=ctx.m)).json()["comment"] == text


@pytest.mark.parametrize(
    "markup", ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "a > b", "a < b"]
)
async def test_markup_in_comment_is_422(api, ctx, markup):
    r = await create(api, ctx, comment=markup)
    assert r.status_code == 422 and "comment" in err(r)["fields"]


async def test_control_chars_stripped_from_comment(api, ctx):
    a = await ok(api, ctx, comment="a\x00b\x1bc\u0007d")
    assert a["comment"] == "abcd"
    a2 = await ok(api, ctx, start_at=at(12), end_at=at(13), comment="\x00")
    assert a2["comment"] is None


async def test_comment_limit_boundary(api, ctx):
    a = await ok(api, ctx, comment="я" * 1000)
    assert len(a["comment"]) == 1000


# ---------------- расширение Location ----------------


async def test_location_read_has_new_fields_for_all_roles(api, ctx):
    for h in (ctx.m, ctx.d, ctx.x):
        r = await api.get(f"{API}/locations/{ctx.a.id}", headers=h)
        assert r.status_code == 200
        loc = r.json()
        assert set(loc) == {
            "id", "name", "address", "phone", "is_active", "code", "timezone", "work_start", "work_end",
            # поля чата точки (расширение модуля 7)
            "has_telegram_chat", "telegram_chat_id",
        }  # fmt: skip
        assert loc["timezone"] == "Europe/Moscow"
        assert loc["work_start"] == "09:00" and loc["work_end"] == "21:00"
        assert loc["code"] == ctx.a.code
    r = await api.get(f"{API}/locations", headers=ctx.m)
    assert [x["id"] for x in r.json()] == [str(ctx.a.id)]
    assert r.json()[0]["work_end"] == "21:00"


async def test_location_create_defaults_and_explicit(api, db, ctx):
    r = await api.post(
        f"{API}/locations", headers=ctx.d, json={"name": "Новая точка", "address": "ул. 1"}
    )
    assert r.status_code == 201, r.text
    loc = r.json()
    assert (
        loc["timezone"] == "Europe/Moscow"
        and loc["work_start"] == "09:00"
        and loc["work_end"] == "21:00"
    )
    assert loc["code"] and loc["code"] == loc["code"].upper()
    r = await api.post(
        f"{API}/locations", headers=ctx.d,
        json={"name": "Дальний", "address": "ул. 2", "timezone": "Asia/Vladivostok", "work_start": "08:30", "work_end": "20:45"},
    )  # fmt: skip
    assert r.status_code == 201
    far = r.json()
    assert (far["timezone"], far["work_start"], far["work_end"]) == (
        "Asia/Vladivostok",
        "08:30",
        "20:45",
    )
    assert (await api.get(f"{API}/locations/{far['id']}", headers=ctx.d)).json() == far
    loc_row = await db.scalar(select(Location).where(Location.id == uuid.UUID(far["id"])))
    assert loc_row.work_start == time(8, 30)
    audit_row = await db.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "location", AuditLog.entity_id == uuid.UUID(far["id"])
        )
    )
    assert audit_row.changes["timezone"]["new"] == "Asia/Vladivostok"
    assert audit_row.changes["work_start"]["new"] == "08:30"


async def test_location_patch_new_fields(api, db, ctx):
    url = f"{API}/locations/{ctx.a.id}"
    r = await api.patch(
        url,
        headers=ctx.d,
        json={"timezone": "Asia/Yekaterinburg", "work_start": "08:00", "work_end": "20:00"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["timezone"], r.json()["work_start"], r.json()["work_end"]) == (
        "Asia/Yekaterinburg",
        "08:00",
        "20:00",
    )
    row = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "location",
                AuditLog.action == "update",
                AuditLog.entity_id == ctx.a.id,
            )
        )
    ).one()
    assert row.changes["timezone"] == {"old": "Europe/Moscow", "new": "Asia/Yekaterinburg"}
    assert row.changes["work_start"] == {"old": "09:00", "new": "08:00"}
    # одно поле
    r = await api.patch(url, headers=ctx.d, json={"work_end": "23:59"})
    assert (
        r.status_code == 200
        and r.json()["work_end"] == "23:59"
        and r.json()["work_start"] == "08:00"
    )
    r = await api.patch(url, headers=ctx.d, json={"work_start": "00:00"})
    assert r.status_code == 200 and r.json()["work_start"] == "00:00"


async def test_location_new_fields_are_director_only(api, ctx):
    url = f"{API}/locations/{ctx.a.id}"
    for h in (ctx.m, ctx.x):
        r = await api.patch(url, headers=h, json={"timezone": "Europe/Moscow"})
        assert r.status_code == 403
    r = await api.post(
        f"{API}/locations", headers=ctx.m, json={"name": "Z", "address": "x", "timezone": "UTC"}
    )
    assert r.status_code == 403


BAD_TZ = [
    "Mars/Phobos",
    "",
    "europe/moscow",
    "../../etc/passwd",
    "Europe/Moscow ",
    "UTC+3",
    "Europe\\Moscow",
    "x" * 100,
    "\x00",
]
BAD_TIME = [
    "9:00",
    "24:00",
    "09:60",
    "09:00:00",
    "ab",
    "",
    "09-00",
    "0900",
    "9",
    " 09:00",
    "09:00 ",
    "٠٩:٠٠",
]


@pytest.mark.parametrize("tz", [*BAD_TZ, 5, None, ["Europe/Moscow"]])
async def test_location_invalid_timezone_is_422(api, ctx, tz):
    r = await api.post(
        f"{API}/locations", headers=ctx.d, json={"name": "Т", "address": "а", "timezone": tz}
    )
    assert r.status_code == 422 and "timezone" in err(r)["fields"]
    r = await api.patch(f"{API}/locations/{ctx.a.id}", headers=ctx.d, json={"timezone": tz})
    assert r.status_code == 422 and (tz is None or "timezone" in err(r)["fields"])


@pytest.mark.parametrize("field", ["work_start", "work_end"])
@pytest.mark.parametrize("value", [*BAD_TIME, 900, None, True])
async def test_location_invalid_time_is_422(api, ctx, field, value):
    r = await api.post(
        f"{API}/locations", headers=ctx.d, json={"name": "Т", "address": "а", field: value}
    )
    assert r.status_code == 422 and field in err(r)["fields"]
    r = await api.patch(f"{API}/locations/{ctx.a.id}", headers=ctx.d, json={field: value})
    assert r.status_code == 422 and (value is None or field in err(r)["fields"])


async def test_location_work_end_must_be_after_start(api, ctx):
    for start, end in [("10:00", "10:00"), ("10:00", "09:59"), ("21:00", "09:00")]:
        r = await api.post(
            f"{API}/locations",
            headers=ctx.d,
            json={"name": "Т", "address": "а", "work_start": start, "work_end": end},
        )
        assert r.status_code == 422 and err(r)["fields"] == {"work_end": "must_be_after_work_start"}
    url = f"{API}/locations/{ctx.a.id}"  # 09:00–21:00
    assert (await api.patch(url, headers=ctx.d, json={"work_end": "09:00"})).status_code == 422
    assert (await api.patch(url, headers=ctx.d, json={"work_start": "21:00"})).status_code == 422
    assert (
        await api.patch(url, headers=ctx.d, json={"work_start": "22:00", "work_end": "23:00"})
    ).status_code == 200
    # после неудачных правок значения не менялись
    r = await api.patch(url, headers=ctx.d, json={"work_end": "22:00"})
    assert r.status_code == 422
    assert (await api.get(url, headers=ctx.d)).json()["work_start"] == "22:00"


async def test_location_extra_fields_still_rejected(api, ctx):
    r = await api.patch(f"{API}/locations/{ctx.a.id}", headers=ctx.d, json={"code": "HACK"})
    assert r.status_code == 422
    r = await api.post(
        f"{API}/locations", headers=ctx.d, json={"name": "Т", "address": "а", "work_hours": "9-21"}
    )
    assert r.status_code == 422


# ---------------- unit: вспомогательные функции сервиса ----------------


class _Orig(Exception):  # noqa: N818
    def __init__(self, sqlstate: str | None = None, pgcode: str | None = None) -> None:
        self.sqlstate, self.pgcode = sqlstate, pgcode


def test_exclusion_violation_detection():
    assert svc._is_exclusion_violation(IntegrityError("x", {}, _Orig("23P01")))
    assert svc._is_exclusion_violation(IntegrityError("x", {}, _Orig(None, "23P01")))
    assert not svc._is_exclusion_violation(IntegrityError("x", {}, _Orig("23505")))
    assert not svc._is_exclusion_violation(IntegrityError("x", {}, _Orig()))


async def test_raise_busy_without_visible_conflict_has_no_details(db):
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    with pytest.raises(AppError) as ei:
        await svc._raise_busy(
            db, post_id=uuid.uuid4(), start=datetime(2026, 11, 10, 7, tzinfo=UTC),
            end=datetime(2026, 11, 10, 8, tzinfo=UTC), tz=ZoneInfo("Europe/Moscow"), exclude_id=None,
        )  # fmt: skip
    assert ei.value.status == 409 and ei.value.code == "post_busy" and ei.value.details is None


async def test_db_constraints_directly(db, ctx):
    """Ограничения БД работают независимо от API."""
    from datetime import UTC, datetime

    def row(**kw) -> Appointment:
        base = {
            "location_id": ctx.a.id, "client_id": ctx.client.id, "vehicle_id": ctx.vehicle.id,
            "post_id": ctx.p1.id, "department": "service",
            "start_at": datetime(2026, 11, 10, 7, tzinfo=UTC), "end_at": datetime(2026, 11, 10, 8, tzinfo=UTC),
            "created_by": ctx.users[0].id,
        }  # fmt: skip
        return Appointment(**{**base, **kw})

    db.add(row())
    await db.commit()
    for bad in (
        row(),  # пересечение
        row(end_at=datetime(2026, 11, 10, 7, tzinfo=UTC), post_id=None),  # end_at = start_at
        row(status="bogus", post_id=None),
        row(department="wash", post_id=None),
    ):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(bad)
                await db.flush()
    # смежная и без поста — можно
    db.add_all(
        [
            row(
                start_at=datetime(2026, 11, 10, 8, tzinfo=UTC),
                end_at=datetime(2026, 11, 10, 9, tzinfo=UTC),
            ),
            row(post_id=None),
            row(status="cancelled"),
        ]
    )
    await db.commit()


# ---------------- гонки: реальные коммиты ----------------


@pytest.fixture
async def real(engine):
    """Клиент на реальных сессиях и коммитах (без отката); данные удаляются после теста."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        c = await seed(s, unique=True)
    app = build_app("test")

    async def override():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override
    transport = httpx.ASGITransport(
        app=app, raise_app_exceptions=False, client=("203.0.113.9", 50000)
    )
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://t") as http:
            yield http, c
    finally:
        get_settings.cache_clear()
        await cleanup(engine, c)


async def cleanup(engine, c: SimpleNamespace) -> None:
    locs = [c.a.id, c.b.id]
    users = [u.id for u in c.users]
    async with AsyncSession(engine) as s:
        appts = select(Appointment.id).where(Appointment.location_id.in_(locs))
        await s.execute(
            delete(AppointmentService).where(AppointmentService.appointment_id.in_(appts))
        )
        await s.execute(delete(Appointment).where(Appointment.location_id.in_(locs)))
        await s.execute(
            delete(AuditLog).where((AuditLog.location_id.in_(locs)) | (AuditLog.user_id.in_(users)))
        )
        clients = [c.client.id, c.other.id, c.archived_client.id]
        await s.execute(delete(Vehicle).where(Vehicle.client_id.in_(clients)))
        await s.execute(delete(Client).where(Client.id.in_(clients)))
        await s.execute(
            delete(Service).where(Service.id.in_([c.s1.id, c.s2.id, c.s_det.id, c.s_off.id]))
        )
        await s.execute(
            delete(ServiceCategory).where(ServiceCategory.id.in_([x.id for x in c.cats]))
        )
        await s.execute(delete(WorkPost).where(WorkPost.location_id.in_(locs)))
        await s.execute(delete(UserLocation).where(UserLocation.user_id.in_(users)))
        await s.execute(delete(User).where(User.id.in_(users)))
        await s.execute(delete(Location).where(Location.id.in_(locs)))
        await s.commit()


async def test_concurrent_create_same_slot_exactly_one_wins(real, engine):
    http, c = real
    rs = await asyncio.gather(
        http.post(APPT, headers=c.m, json=body(c)),
        http.post(APPT, headers=c.d, json=body(c)),
    )
    assert sorted(r.status_code for r in rs) == [201, 409], [r.text for r in rs]
    winner = next(r for r in rs if r.status_code == 201).json()
    loser = next(r for r in rs if r.status_code == 409)
    assert err(loser)["code"] == "post_busy"
    assert err(loser)["details"]["conflict_id"] == winner["id"]
    async with AsyncSession(engine) as s:
        rows = list(await s.scalars(select(Appointment).where(Appointment.location_id == c.a.id)))
        assert [str(r.id) for r in rows] == [winner["id"]]
        assert await s.scalar(select(func.count()).select_from(AppointmentService)) is not None


async def test_concurrent_create_many_overlapping_one_wins(real, engine):
    http, c = real
    slots = [
        (10, 0, 11, 0),
        (10, 30, 11, 30),
        (10, 15, 10, 45),
        (9, 30, 10, 15),
        (10, 50, 11, 5),
        (10, 0, 11, 0),
    ]
    rs = await asyncio.gather(
        *(
            http.post(
                APPT,
                headers=c.m,
                json=body(c, start_at=at(a, b), end_at=at(d, e), service_ids=[str(c.s1.id)]),
            )
            for a, b, d, e in slots
        )
    )
    codes = sorted(r.status_code for r in rs)
    assert codes.count(201) >= 1 and set(codes) <= {201, 409}, [r.text for r in rs]
    async with AsyncSession(engine) as s:
        rows = list(
            await s.scalars(
                select(Appointment)
                .where(Appointment.location_id == c.a.id)
                .order_by(Appointment.start_at)
            )
        )
    assert len(rows) == codes.count(201)
    # в базе нет ни одной пары пересекающихся записей
    for i, x in enumerate(rows):
        for y in rows[i + 1 :]:
            assert x.end_at <= y.start_at or y.end_at <= x.start_at


async def test_concurrent_back_to_back_both_succeed(real):
    http, c = real
    rs = await asyncio.gather(
        http.post(APPT, headers=c.m, json=body(c, start_at=at(10), end_at=at(11))),
        http.post(APPT, headers=c.m, json=body(c, start_at=at(11), end_at=at(12))),
    )
    assert [r.status_code for r in rs] == [201, 201]


async def test_concurrent_different_posts_both_succeed(real):
    http, c = real
    rs = await asyncio.gather(
        http.post(APPT, headers=c.m, json=body(c, post_id=str(c.p1.id))),
        http.post(APPT, headers=c.m, json=body(c, post_id=str(c.p2.id))),
    )
    assert [r.status_code for r in rs] == [201, 201]


async def test_concurrent_move_into_same_slot_one_wins(real):
    http, c = real
    a = (await http.post(APPT, headers=c.m, json=body(c, start_at=at(9), end_at=at(10)))).json()
    b = (await http.post(APPT, headers=c.m, json=body(c, start_at=at(12), end_at=at(13)))).json()
    target = {"start_at": at(15), "end_at": at(16)}
    rs = await asyncio.gather(
        http.patch(f"{APPT}/{a['id']}", headers=c.m, json=target),
        http.patch(f"{APPT}/{b['id']}", headers=c.m, json=target),
    )
    assert sorted(r.status_code for r in rs) == [200, 409], [r.text for r in rs]
    assert err(next(r for r in rs if r.status_code == 409))["code"] == "post_busy"
