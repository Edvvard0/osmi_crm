"""Модуль 7: Telegram-уведомления, outbox, воркер, бот (без сети: httpx.MockTransport)."""

# ruff: noqa: E501

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import periodic
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.security import create_access_token
from app.models import AuditLog, Client, Role, User, Vehicle
from app.models.appointment import Appointment
from app.models.telegram import NotificationOutbox, TelegramLinkCode
from app.models.work_order import WorkOrder
from app.services import appointments as appt_svc
from app.services import notification_catalog as cat
from app.services import outbox, telegram, telegram_client
from app.services.audit import ClientInfo
from app.services.events import publish
from app.services.sessions import utcnow
from tests.factories import bearer, make_location, make_user

pytestmark = pytest.mark.integration

API = "/api/v1"
SECRET = "s" * 40
HOOK = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


def token(user: User) -> dict[str, str]:
    return bearer(create_access_token(user.id)[0])


class FakeBot:
    """Мок Bot API: запоминает sendMessage и отвечает по `responder`."""

    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.responder: Callable[[int], tuple[int, dict[str, object]]] = lambda chat: (
            200,
            {"ok": True, "result": {}},
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/sendMessage"):
            self.sent.append(body)
            status, js = self.responder(int(body["chat_id"]))
            return httpx.Response(status, json=js)
        return httpx.Response(200, json={"ok": True, "result": True})

    def texts(self, chat_id: int) -> list[str]:
        return [str(m["text"]) for m in self.sent if m["chat_id"] == chat_id]


@pytest.fixture
def tg_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "TELEGRAM_BOT_TOKEN": "123456:TEST-TOKEN-VALUE",
        "TELEGRAM_BOT_USERNAME": "crm_test_bot",
        "TELEGRAM_MODE": "webhook",
        "TELEGRAM_WEBHOOK_SECRET": SECRET,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    telegram.link_code_limiter.reset()
    telegram.test_limiter.reset()
    telegram.bot_link_limiter.reset()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def bot(tg_env: None) -> AsyncIterator[FakeBot]:
    fake = FakeBot()
    telegram_client.set_transport(httpx.MockTransport(fake.handler))
    yield fake
    await telegram_client.close_client()
    telegram_client.set_transport(None)


async def bind(db: AsyncSession, user: User, chat_id: int, username: str | None = None) -> User:
    user.telegram_chat_id = chat_id
    user.telegram_username = username
    await db.commit()
    return user


def next_chat() -> int:
    return 10_000_000 + uuid.uuid4().int % 1_000_000_000


async def outbox_rows(db: AsyncSession, event_type: str | None = None) -> list[NotificationOutbox]:
    stmt = select(NotificationOutbox).order_by(NotificationOutbox.id)
    if event_type:
        stmt = stmt.where(NotificationOutbox.event_type == event_type)
    return list((await db.scalars(stmt)).all())


async def retry_now(db: AsyncSession, row_id: int) -> None:
    await db.execute(
        text("UPDATE notification_outbox SET next_attempt_at = now() - interval '1 second' WHERE id = :i"),
        {"i": row_id},
    )
    await db.commit()


async def webhook(api: httpx.AsyncClient, update_body: dict[str, object], headers=HOOK) -> httpx.Response:  # noqa: ANN001
    return await api.post(f"{API}/telegram/webhook", json=update_body, headers=headers)


def msg(chat_id: int, text_: str, chat_type: str = "private", username: str | None = "ivan") -> dict[str, object]:
    return {
        "update_id": 1,
        "message": {"chat": {"id": chat_id, "type": chat_type}, "from": {"username": username}, "text": text_},
    }


# ---------------- события и получатели ----------------


async def test_publish_recipients_group_dedup_and_settings(db: AsyncSession, tg_env: None) -> None:
    loc = await make_location(db)
    group = -100500123
    loc.telegram_chat_id = group
    other_loc = await make_location(db)
    actor = await bind(db, await make_user(db, Role.manager, locations=[loc]), next_chat())
    m1 = await bind(db, await make_user(db, Role.manager, locations=[loc]), next_chat())
    m2 = await bind(db, await make_user(db, Role.manager, locations=[loc]), next_chat())
    await bind(db, await make_user(db, Role.manager, locations=[other_loc]), next_chat())  # чужая точка
    await make_user(db, Role.manager, locations=[loc])  # не привязан к Telegram
    await bind(db, await make_user(db, Role.manager, locations=[loc], is_active=False), next_chat())

    payload = {"appointment_id": "a1", "start_at": "2026-11-10T12:00:00+00:00", "plate_number": "А<1>", "make": "Kia", "model": "Rio", "services_count": 2, "created_by_name": "Иван & Ко"}
    await publish(db, "appointment.created", payload, location_id=loc.id, actor_id=actor.id)
    await db.commit()
    rows = await outbox_rows(db, "appointment.created")
    assert {r.user_id for r in rows} == {m1.id, m2.id}  # создавший и группа не получают
    assert "Иван &amp; Ко" in rows[0].text and "А&lt;1&gt;" in rows[0].text

    # no_show: менеджеры + групповой чат; дубль по dedup_key игнорируется
    for _ in range(2):
        await publish(db, "appointment.no_show", {"appointment_id": "a1", "start_at": payload["start_at"], "plate_number": "A1"}, location_id=loc.id, actor_id=actor.id, dedup_key="appointment.no_show:a1")
        await db.commit()
    rows = await outbox_rows(db, "appointment.no_show")
    assert len(rows) == 4  # actor, m1, m2 и группа
    assert [r.chat_id for r in rows if r.user_id is None] == [group]

    # отключённое событие не доставляется
    await db.execute(text("INSERT INTO notification_settings (user_id, event_type, is_enabled) VALUES (:u, 'appointment.created', false)"), {"u": m1.id})
    await db.commit()
    await publish(db, "appointment.created", payload, location_id=loc.id, actor_id=actor.id)
    await db.commit()
    assert len([r for r in await outbox_rows(db, "appointment.created") if r.user_id == m1.id]) == 1
    assert len([r for r in await outbox_rows(db, "appointment.created") if r.user_id == m2.id]) == 2


async def test_publish_disabled_and_templates(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    loc = await make_location(db)
    director = await bind(db, await make_user(db, Role.director), next_chat())
    await publish(db, "user.locked", {"login": "x"}, location_id=None, actor_id=None)
    await db.commit()
    assert await outbox_rows(db) == []
    get_settings.cache_clear()

    # шаблоны: экранирование, пояс точки, обрезка до 4096
    tz = ZoneInfo("Europe/Moscow")
    assert cat.fmt_dt("2026-11-10T09:30:00+00:00", tz) == "10.11 12:30"
    assert cat.fmt_money("1500") == "1 500.00"
    assert "&lt;b&gt;" in cat.CATALOG["part_request.created"].render({"description": "<b>", "quantity": 1}, tz)
    long = cat.truncate("<b>" + "я" * 5000 + "</b>")
    assert len(long) <= 4096 and long.endswith("</b>") and "…" in long
    assert director.id and loc.id


# ---------------- настройки уведомлений ----------------


async def test_notification_settings_api(api: httpx.AsyncClient, db: AsyncSession, tg_env: None) -> None:
    loc = await make_location(db)
    manager = await make_user(db, Role.manager, locations=[loc])
    mechanic = await make_user(db, Role.mechanic, locations=[loc])
    url = f"{API}/telegram/notification-settings"

    r = await api.get(url, headers=token(manager))
    assert r.status_code == 200 and len(r.json()) == 7 and all(s["is_default"] and s["is_enabled"] for s in r.json())
    assert [s["event_type"] for s in (await api.get(url, headers=token(mechanic))).json()] == ["work_item.assigned", "work_item.updated", "part_request.handled"]

    r = await api.patch(url, headers=token(manager), json={"items": [{"event_type": "stock.low", "is_enabled": False}]})
    assert r.status_code == 200
    stock = next(s for s in r.json() if s["event_type"] == "stock.low")
    assert stock["is_enabled"] is False and stock["is_default"] is False

    # чужое для роли, неизвестное, пустое, лишние поля
    for body in (
        {"items": [{"event_type": "payment.refund", "is_enabled": True}]},
        {"items": [{"event_type": "nope", "is_enabled": True}]},
        {"items": []},
        {"items": [{"event_type": "stock.low", "is_enabled": True, "user_id": "x"}]},
    ):
        r = await api.patch(url, headers=token(manager), json=body)
        assert r.status_code == 422, body
    assert (await api.patch(url, headers=token(manager), json={"items": [{"event_type": "payment.refund", "is_enabled": True}]})).json()["error"]["fields"] == {"items": "unknown_event"}
    assert (await api.get(url)).status_code == 401


# ---------------- привязка аккаунта и бот ----------------


async def test_link_code_flow_and_bot_binding(api: httpx.AsyncClient, db: AsyncSession, bot: FakeBot) -> None:
    loc = await make_location(db)
    user = await make_user(db, Role.manager, locations=[loc], )
    other = await make_user(db, Role.mechanic, locations=[loc])

    r = await api.get(f"{API}/telegram/status", headers=token(user))
    assert r.json() == {"enabled": True, "bot_username": "crm_test_bot", "linked": False, "telegram_username": None}

    r = await api.post(f"{API}/telegram/link-code", headers=token(user), json={})
    assert r.status_code == 201
    code = r.json()["code"]
    assert re.fullmatch(r"[A-HJKMNP-Z2-9]{8}", code) and r.json()["link"] == f"https://t.me/crm_test_bot?start={code}"
    stored = (await db.scalars(select(TelegramLinkCode).where(TelegramLinkCode.user_id == user.id))).all()
    assert len(stored) == 1 and stored[0].code_hash != code and len(stored[0].code_hash) == 64

    # новый код аннулирует прежний
    code2 = (await api.post(f"{API}/telegram/link-code", headers=token(user), json={})).json()["code"]
    chat = next_chat()
    assert (await webhook(api, msg(chat, f"/start {code}"))).json() == {}
    assert "Код не подходит" in bot.texts(chat)[-1]

    # группа/канал привязать не могут; /start без кода — справка
    assert (await webhook(api, msg(chat, f"/start {code2}", chat_type="group"))).status_code == 200
    assert bot.texts(chat)[-1].startswith("Код не подходит")  # новых ответов нет
    n = len(bot.sent)
    await webhook(api, msg(chat, "/help"))
    assert "/stop" in bot.texts(chat)[-1] and len(bot.sent) == n + 1

    await webhook(api, msg(chat, f"/start {code2.lower()}", username="ivan_p"))
    assert bot.texts(chat)[-1].startswith("Готово, ")
    await db.refresh(user)
    assert user.telegram_chat_id == chat and user.telegram_username == "ivan_p"
    audit = await db.scalar(select(AuditLog).where(AuditLog.entity_id == user.id, AuditLog.action == "update"))
    assert audit is not None and audit.changes == {"telegram_linked": {"old": False, "new": True}}

    # одноразовость и уже привязан
    await webhook(api, msg(chat, f"/start {code2}"))
    assert bot.texts(chat)[-1].startswith("Код не подходит")
    r = await api.post(f"{API}/telegram/link-code", headers=token(user), json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_linked"
    assert (await api.get(f"{API}/telegram/status", headers=token(user))).json()["linked"] is True

    # чат уже занят другим сотрудником
    code3 = (await api.post(f"{API}/telegram/link-code", headers=token(other), json={})).json()["code"]
    await webhook(api, msg(chat, f"/start {code3}"))
    assert bot.texts(chat)[-1] == "Этот чат уже привязан к другому сотруднику"
    await db.refresh(other)
    assert other.telegram_chat_id is None

    # /stop в чате отвязывает; повторный /stop безвреден
    await webhook(api, msg(chat, "/stop"))
    await db.refresh(user)
    assert user.telegram_chat_id is None and user.telegram_username is None
    await webhook(api, msg(chat, "/stop"))

    # истёкший код
    expired = telegram.new_code()
    db.add(TelegramLinkCode(user_id=other.id, code_hash=telegram.code_hash(expired), expires_at=utcnow() - timedelta(seconds=1)))
    await db.commit()
    await webhook(api, msg(chat, f"/start {expired}"))
    assert bot.texts(chat)[-1].startswith("Код не подходит")

    # лимит запросов кода: 5 в минуту на пользователя
    third = await make_user(db, Role.mechanic, locations=[loc])
    statuses = [(await api.post(f"{API}/telegram/link-code", headers=token(third), json={})).status_code for _ in range(6)]
    assert statuses == [201] * 5 + [429]


async def test_link_code_disabled_and_webhook_security(api: httpx.AsyncClient, db: AsyncSession, bot: FakeBot, monkeypatch: pytest.MonkeyPatch) -> None:
    user = await make_user(db, Role.manager, locations=[await make_location(db)])
    for headers in ({}, {"X-Telegram-Bot-Api-Secret-Token": "wrong"}, {"X-Telegram-Bot-Api-Secret-Token": SECRET + "x"}):
        assert (await webhook(api, msg(1, "/help"), headers)).status_code == 403
    assert bot.sent == []
    assert (await api.post(f"{API}/telegram/webhook", content=b"not json", headers=HOOK)).json() == {}
    assert (await webhook(api, {"edited_message": {}})).json() == {}

    # /chatid отвечает в любом чате, в том числе в группе
    await webhook(api, msg(-100777, "/chatid@crm_test_bot", chat_type="supergroup"))
    assert bot.texts(-100777) == ["ID этого чата: -100777"]

    # режим polling: вебхук отвечает 404
    monkeypatch.setenv("TELEGRAM_MODE", "polling")
    get_settings.cache_clear()
    assert (await webhook(api, msg(1, "/help"))).status_code == 404
    monkeypatch.setenv("TELEGRAM_MODE", "webhook")
    # Telegram выключен -> 409 telegram_disabled
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    r = await api.post(f"{API}/telegram/link-code", headers=token(user), json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "telegram_disabled"
    st = (await api.get(f"{API}/telegram/status", headers=token(user))).json()
    assert st["enabled"] is False and st["bot_username"] is None


async def test_unlink_api_and_user_fields(api: httpx.AsyncClient, db: AsyncSession, tg_env: None) -> None:
    loc = await make_location(db)
    user = await bind(db, await make_user(db, Role.manager, locations=[loc]), next_chat(), "ivan")
    director = await make_user(db, Role.director)
    await publish(db, "user.locked", {"login": "x", "full_name": "y", "locked_until": utcnow().isoformat()}, location_id=None, actor_id=None)
    db.add(NotificationOutbox(event_type="stock.low", user_id=user.id, chat_id=user.telegram_chat_id, payload={}, text="t"))
    await db.commit()

    me = (await api.get(f"{API}/auth/me", headers=token(user))).json()
    assert me["telegram_linked"] is True and me["telegram_username"] == "ivan"
    listed = (await api.get(f"{API}/users?search={user.login}", headers=token(director))).json()["items"][0]
    assert listed["telegram_linked"] is True

    for _ in range(2):  # идемпотентно
        assert (await api.delete(f"{API}/telegram/link", headers=token(user))).status_code == 204
    await db.refresh(user)
    assert user.telegram_chat_id is None and user.telegram_username is None
    rows = [r for r in await outbox_rows(db) if r.user_id == user.id]
    assert [r.status for r in rows] == ["skipped"]
    audits = (await db.scalars(select(AuditLog).where(AuditLog.entity_id == user.id, AuditLog.action == "update"))).all()
    assert len(audits) == 1 and audits[0].changes == {"telegram_linked": {"old": True, "new": False}}
    assert (await api.get(f"{API}/auth/me", headers=token(user))).json()["telegram_linked"] is False


# ---------------- отправка из outbox ----------------


def clock_throttle() -> tuple[outbox.Throttle, SimpleNamespace]:
    state = SimpleNamespace(now=1000.0, slept=0.0)

    async def sleep(seconds: float) -> None:
        state.slept += seconds
        state.now += seconds

    return outbox.Throttle(clock=lambda: state.now, sleep=sleep), state


async def test_dispatch_success_throttle_and_order(db: AsyncSession, bot: FakeBot) -> None:
    chat_a, chat_b = next_chat(), next_chat()
    user_a = await bind(db, await make_user(db, Role.director), chat_a)
    for chat, uid, label in ((chat_a, user_a.id, "a1"), (chat_a, user_a.id, "a2"), (chat_b, None, "b1")):
        db.add(NotificationOutbox(event_type="stock.low", user_id=uid, chat_id=chat, payload={}, text=label))
    await db.commit()
    throttle, state = clock_throttle()

    # одна пачка: по одному сообщению на чат; чат остывает 1 с
    assert await outbox.dispatch_once(db, telegram_client.get_client(), throttle) == 2
    assert [m["text"] for m in bot.sent] == ["a1", "b1"] and bot.sent[0]["parse_mode"] == "HTML"
    assert await outbox.dispatch_once(db, telegram_client.get_client(), throttle) == 0
    state.now += 1.5
    assert await outbox.dispatch_once(db, telegram_client.get_client(), throttle) == 1
    assert bot.texts(chat_a) == ["a1", "a2"]
    rows = await outbox_rows(db)
    assert [r.status for r in rows] == ["sent"] * 3 and all(r.sent_at for r in rows)
    assert state.slept > 0  # общий лимит 30/с обеспечен паузами


async def test_dispatch_retry_backoff_failed_and_rate_limit(db: AsyncSession, bot: FakeBot) -> None:
    chat = next_chat()
    row = NotificationOutbox(event_type="stock.low", user_id=None, chat_id=chat, payload={}, text="x")
    db.add(row)
    await db.commit()
    throttle, state = clock_throttle()
    client = telegram_client.get_client()
    bot.responder = lambda c: (502, {"ok": False, "description": "Bad Gateway"})

    started = utcnow()
    assert await outbox.dispatch_once(db, client, throttle) == 1
    await db.refresh(row)
    assert (row.status, row.attempts) == ("pending", 1)
    assert timedelta(seconds=25) < row.next_attempt_at - started < timedelta(seconds=40)
    assert "123456:TEST" not in (row.last_error or "")
    assert await outbox.dispatch_once(db, client, throttle) == 0  # ещё рано

    expected = [60, 120, 240]
    for delay in expected:
        await retry_now(db, row.id)
        await outbox.dispatch_once(db, client, throttle)
        await db.refresh(row)
        assert row.status == "pending"
        assert abs((row.next_attempt_at - utcnow()).total_seconds() - delay) < 10
    await retry_now(db, row.id)
    await outbox.dispatch_once(db, client, throttle)
    await db.refresh(row)
    assert (row.status, row.attempts) == ("failed", 5) and row.last_error.startswith("temporary")

    # 429: не раньше retry_after; другие 4xx — сразу failed
    r429 = NotificationOutbox(event_type="stock.low", user_id=None, chat_id=next_chat(), payload={}, text="y")
    bad = NotificationOutbox(event_type="stock.low", user_id=None, chat_id=next_chat(), payload={}, text="z")
    db.add_all([r429, bad])
    await db.commit()
    bot.responder = lambda c: (429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 300}}) if c == r429.chat_id else (400, {"ok": False, "description": "Bad Request: can't parse entities"})
    await outbox.dispatch_once(db, client, throttle)
    await db.refresh(r429)
    await db.refresh(bad)
    assert r429.status == "pending" and (r429.next_attempt_at - utcnow()).total_seconds() > 280
    assert bad.status == "failed"


async def test_dispatch_blocked_clears_chat_and_skips_pending(db: AsyncSession, bot: FakeBot) -> None:
    chat = next_chat()
    user = await bind(db, await make_user(db, Role.director), chat, "ivan")
    loc = await make_location(db)
    group = -1009990001
    loc.telegram_chat_id = group
    await db.commit()
    db.add_all([
        NotificationOutbox(event_type="stock.low", user_id=user.id, chat_id=chat, payload={}, text="1"),
        NotificationOutbox(event_type="stock.low", user_id=user.id, chat_id=chat, payload={}, text="2"),
        NotificationOutbox(event_type="stock.low", user_id=None, chat_id=group, payload={}, text="g"),
    ])
    await db.commit()
    bot.responder = lambda c: (403, {"ok": False, "description": "Forbidden: bot was blocked by the user"}) if c == chat else (400, {"ok": False, "description": "Bad Request: chat not found"})
    throttle, _ = clock_throttle()
    await outbox.dispatch_once(db, telegram_client.get_client(), throttle)
    await db.refresh(user)
    await db.refresh(loc)
    assert user.telegram_chat_id is None and user.telegram_username is None
    assert loc.telegram_chat_id is None
    rows = await outbox_rows(db)
    assert [(r.status, r.last_error) for r in rows] == [("skipped", "blocked")] * 3
    kinds = {a.entity_type for a in (await db.scalars(select(AuditLog).where(AuditLog.action == "update"))).all()}
    assert {"user", "location"} <= kinds


async def test_overdue_scan_cleanup_and_hooks(db: AsyncSession, bot: FakeBot) -> None:
    loc = await make_location(db)
    manager = await bind(db, await make_user(db, Role.manager, locations=[loc]), next_chat())
    other = await bind(db, await make_user(db, Role.manager, locations=[loc]), next_chat())
    client = Client(client_type="person", full_name="Иван", phone="+79" + str(uuid.uuid4().int)[:9])
    db.add(client)
    await db.flush()
    vehicle = Vehicle(client_id=client.id, make="Kia", model="Rio", plate_number="A123BC")
    db.add(vehicle)
    await db.flush()

    def order(num: str, status: str, hours: int) -> WorkOrder:
        return WorkOrder(number=num, location_id=loc.id, client_id=client.id, vehicle_id=vehicle.id, department="service", status=status, manager_id=manager.id, planned_ready_at=utcnow() - timedelta(hours=hours))

    late, ready, future = order(f"ЗН-{uuid.uuid4().hex[:6]}", "in_progress", 2), order(f"ЗН-{uuid.uuid4().hex[:6]}", "ready", 2), order(f"ЗН-{uuid.uuid4().hex[:6]}", "in_progress", -3)
    db.add_all([late, ready, future])
    await db.commit()

    assert await outbox.overdue_scan(db) >= 1
    assert await outbox.overdue_scan(db) >= 1  # повтор не дублирует
    rows = await outbox_rows(db, "work_order.overdue")
    assert [r.user_id for r in rows] == [manager.id] and late.number in rows[0].text and "A123BC" in rows[0].text

    # хук no_show: смена статуса записи публикует событие менеджерам точки и в группу
    loc.telegram_chat_id = -1008880002
    appt = Appointment(location_id=loc.id, client_id=client.id, vehicle_id=vehicle.id, department="service", start_at=utcnow() + timedelta(hours=3), end_at=utcnow() + timedelta(hours=4), status="scheduled", created_by=manager.id)
    db.add(appt)
    await db.commit()
    await appt_svc.change_status(db, manager, [loc.id], appt.id, "no_show", ClientInfo())
    no_show = await outbox_rows(db, "appointment.no_show")
    assert {r.user_id for r in no_show} == {manager.id, other.id, None}

    # хук appointment.created: создавший не получает
    from app.services.appointment_events import publish_created

    await publish_created(db, appt, manager)
    await db.commit()
    assert [r.user_id for r in await outbox_rows(db, "appointment.created")] == [other.id]

    # очистка: старые sent/skipped/failed удаляются, pending остаётся
    await db.execute(text("UPDATE notification_outbox SET status = 'sent', created_at = now() - interval '31 days' WHERE event_type = 'appointment.no_show' AND user_id IS NULL"))
    await db.commit()
    assert await outbox.cleanup(db) == 1
    assert len(await outbox_rows(db, "appointment.no_show")) == 2


async def test_user_locked_hook(api: httpx.AsyncClient, db: AsyncSession, tg_env: None) -> None:
    director = await bind(db, await make_user(db, Role.director), next_chat())
    victim = await make_user(db, Role.manager, locations=[await make_location(db)])
    for _ in range(get_settings().max_failed_logins + 1):
        await api.post(f"{API}/auth/login", json={"login": victim.login, "password": "wrong-password-123"})
    rows = await outbox_rows(db, "user.locked")
    assert [r.user_id for r in rows] == [director.id] and victim.login in rows[0].text


# ---------------- воркер ----------------


async def test_worker_registry_and_advisory_lock(tg_env: None) -> None:
    try:
        async with periodic.advisory_lock("m7-test-lock") as first:
            async with periodic.advisory_lock("m7-test-lock") as second:
                assert first is True and second is False
            async with periodic.advisory_lock("m7-other-lock") as other:
                assert other is True
        async with periodic.advisory_lock("m7-test-lock") as again:
            assert again is True  # блокировка освобождается

        calls: list[str] = []

        async def ok() -> None:
            calls.append("ok")

        async def boom() -> None:
            raise RuntimeError("secret detail")

        assert await periodic.run_once(periodic.PeriodicTask("m7-ok", ok, interval=1)) is True
        assert await periodic.run_once(periodic.PeriodicTask("m7-boom", boom, interval=1)) is True  # ошибка не падает
        async with periodic.advisory_lock("m7-ok") as held:
            assert held is True
            assert await periodic.run_once(periodic.PeriodicTask("m7-ok", ok, interval=1)) is False
        assert calls == ["ok"]

        # цикл: на сигнал остановки завершается
        stop = asyncio.Event()
        looped = asyncio.create_task(periodic.run_loop(periodic.PeriodicTask("m7-loop", ok, interval=30), stop))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(looped, 5)
        assert calls.count("ok") == 2
    finally:
        await dispose_engine()

    from datetime import UTC, datetime, time

    nxt = periodic.next_daily_run(datetime(2026, 11, 10, 0, 0, tzinfo=UTC), time(3, 30), "Europe/Moscow")
    assert nxt == datetime(2026, 11, 10, 0, 30, tzinfo=UTC)
    nxt = periodic.next_daily_run(datetime(2026, 11, 10, 1, 0, tzinfo=UTC), time(3, 30), "Europe/Moscow")
    assert nxt == datetime(2026, 11, 11, 0, 30, tzinfo=UTC)
    from app import worker

    assert {"outbox_dispatch", "overdue_scan", "outbox_cleanup"} <= set(worker.load_tasks())
    with pytest.raises(ValueError):
        periodic.register("bad", ok)


# ---------------- точка: групповой чат ----------------


async def test_location_chat_fields_and_telegram_test(api: httpx.AsyncClient, db: AsyncSession, bot: FakeBot) -> None:
    loc = await make_location(db, "Точка <Север>")
    director = await make_user(db, Role.director)
    manager = await make_user(db, Role.manager, locations=[loc])
    url = f"{API}/locations/{loc.id}"

    r = await api.post(f"{url}/telegram-test", headers=token(director), json={})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"telegram_chat_id": "required"}
    assert (await api.post(f"{url}/telegram-test", headers=token(manager), json={})).status_code == 403

    for bad in ("123", 1.5, True, 2**63):
        assert (await api.patch(url, headers=token(director), json={"telegram_chat_id": bad})).status_code == 422
    assert (await api.patch(url, headers=token(manager), json={"telegram_chat_id": 5})).status_code == 403

    r = await api.patch(url, headers=token(director), json={"telegram_chat_id": -1001234567890})
    assert r.status_code == 200 and r.json()["telegram_chat_id"] == -1001234567890 and r.json()["has_telegram_chat"] is True
    audit = await db.scalar(select(AuditLog).where(AuditLog.entity_id == loc.id, AuditLog.action == "update"))
    assert audit is not None and "telegram_chat_id" in audit.changes

    m = (await api.get(url, headers=token(manager))).json()
    assert m["has_telegram_chat"] is True and m["telegram_chat_id"] is None
    assert (await api.get(url, headers=token(director))).json()["telegram_chat_id"] == -1001234567890
    assert (await api.get(f"{API}/locations", headers=token(manager))).json()[0]["telegram_chat_id"] is None

    r = await api.post(f"{url}/telegram-test", headers=token(director), json={})
    assert r.status_code == 200 and r.json() == {"sent": True}
    assert bot.texts(-1001234567890) == ["Проверка связи: точка Точка &lt;Север&gt;"]

    # ошибка Bot API: 502 без деталей, чат остаётся записанным
    bot.responder = lambda c: (403, {"ok": False, "description": "Forbidden: bot was kicked from the group chat"})
    r = await api.post(f"{url}/telegram-test", headers=token(director), json={})
    assert r.status_code == 502 and r.json()["error"]["code"] == "telegram_unavailable" and "kicked" not in r.text
    await db.refresh(loc)
    assert loc.telegram_chat_id == -1001234567890

    # лимит 5 в минуту (2 запроса уже дошли до лимитера)
    codes = [(await api.post(f"{url}/telegram-test", headers=token(director), json={})).status_code for _ in range(4)]
    assert codes == [502, 502, 502, 429]

    r = await api.patch(url, headers=token(director), json={"telegram_chat_id": None})
    assert r.json()["has_telegram_chat"] is False
