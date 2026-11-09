"""Каталог событий уведомлений (api-contract-m7.md, «Каталог событий»): получатели и тексты."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

MAX_TEXT = 4096

Payload = dict[str, Any]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def fmt_dt(value: Any, tz: ZoneInfo) -> str:
    """ISO-время -> `DD.MM HH:MM` в поясе точки; нераспознанное значение возвращается как есть."""
    if value in (None, ""):
        return ""
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return esc(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz).strftime("%d.%m %H:%M")


def fmt_money(value: Any) -> str:
    """`1500` -> `1 500.00` (пробел как разделитель тысяч)."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return esc(value)
    return f"{d:,.2f}".replace(",", " ")


def truncate(text: str, limit: int = MAX_TEXT) -> str:
    """Обрезает до `limit` символов с `…`, не оставляя оборванных тегов и сущностей."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1 - len("</b>")]
    lt, gt = cut.rfind("<"), cut.rfind(">")
    if lt > gt:
        cut = cut[:lt]
    amp, semi = cut.rfind("&"), cut.rfind(";")
    if amp > semi:
        cut = cut[:amp]
    cut += "…"
    if cut.count("<b>") > cut.count("</b>"):
        cut += "</b>"
    return cut


Render = Callable[[Payload, ZoneInfo], str]


def _assigned(p: Payload, tz: ZoneInfo) -> str:
    planned = fmt_dt(p.get("planned_ready_at"), tz) or "не задан"
    return (
        f"Вам назначена работа: <b>{esc(p.get('item_name'))}</b>. "
        f"{esc(p.get('make'))} {esc(p.get('model'))} {esc(p.get('plate_number'))}. "
        f"Заказ {esc(p.get('order_number'))}. Срок: {planned}"
    )


def _updated(p: Payload, tz: ZoneInfo) -> str:
    change = p.get("change")
    if change == "deadline":
        what = f"новый срок {fmt_dt(p.get('planned_ready_at'), tz) or 'не задан'}"
    elif change == "comment":
        what = "добавлен комментарий"
    else:
        what = "работа возвращена в исполнение"
    return (
        f"Изменение по работе «{esc(p.get('item_name'))}», "
        f"заказ {esc(p.get('order_number'))}: {what}"
    )


def _part_handled(p: Payload, tz: ZoneInfo) -> str:
    status = p.get("status")
    if status == "approved":
        what = "одобрена"
    elif status == "rejected":
        what = f"отклонена: {esc(p.get('reject_reason'))}"
    else:
        what = "выдана"
    return f"Заявка «{esc(p.get('description'))}» ({esc(p.get('order_number'))}): {what}"


def _appt_created(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Новая запись: {fmt_dt(p.get('start_at'), tz)} {esc(p.get('make'))} {esc(p.get('model'))} "
        f"{esc(p.get('plate_number'))}, услуг: {esc(p.get('services_count'))}. "
        f"Создал: {esc(p.get('created_by_name'))}"
    )


def _no_show(p: Payload, tz: ZoneInfo) -> str:
    return f"Клиент не приехал: {fmt_dt(p.get('start_at'), tz)} {esc(p.get('plate_number'))}"


def _item_finished(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"{esc(p.get('mechanic_name'))} завершил(а) работу «{esc(p.get('item_name'))}», "
        f"заказ {esc(p.get('order_number'))}"
    )


def _ready_for_check(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Заказ {esc(p.get('order_number'))} ({esc(p.get('plate_number'))}): "
        "все работы выполнены, нужна проверка"
    )


def _part_created(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Заявка на запчасть: {esc(p.get('description'))} × {esc(p.get('quantity'))}, "
        f"заказ {esc(p.get('order_number'))}, {esc(p.get('mechanic_name'))}"
    )


def _overdue(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Просрочен заказ {esc(p.get('order_number'))} ({esc(p.get('plate_number'))}), "
        f"срок был {fmt_dt(p.get('planned_ready_at'), tz)}"
    )


def _stock_low(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Остаток ниже минимума: {esc(p.get('name'))} ({esc(p.get('sku'))}) — "
        f"{esc(p.get('quantity'))} при минимуме {esc(p.get('min_quantity'))}, "
        f"{esc(p.get('location_name'))}"
    )


def _refund(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Возврат {fmt_money(p.get('amount'))} ₽ по заказу {esc(p.get('order_number'))} "
        f"({esc(p.get('location_name'))}), оформил {esc(p.get('user_name'))}. "
        f"Причина: {esc(p.get('reason'))}"
    )


def _discount(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Скидка {esc(p.get('discount_percent'))}% в заказе {esc(p.get('order_number'))} "
        f"({esc(p.get('location_name'))}), {esc(p.get('user_name'))}"
    )


def _locked(p: Payload, tz: ZoneInfo) -> str:
    return (
        f"Учётная запись {esc(p.get('login'))} ({esc(p.get('full_name'))}) заблокирована "
        f"после неудачных попыток входа до {fmt_dt(p.get('locked_until'), tz)}"
    )


def _daily(p: Payload, tz: ZoneInfo) -> str:
    place = f" ({esc(p.get('location_name'))})" if p.get("location_name") else ""
    text = (
        f"Итоги дня {esc(p.get('date'))}{place}: выручка {fmt_money(p.get('revenue'))} ₽, "
        f"закрыто заказов {esc(p.get('orders_closed'))}, в работе {esc(p.get('orders_open'))}, "
        f"касса {fmt_money(p.get('cash_received'))} ₽"
    )
    if p.get("breakdown"):
        text += "\n" + esc(p["breakdown"])
    return text


@dataclass(frozen=True)
class EventDef:
    event_type: str
    title: str
    description: str
    # target | location_managers | location_managers_except_actor | order_manager | directors
    recipients: str
    group: bool
    render: Render


def _def(
    event_type: str,
    title: str,
    description: str,
    recipients: str,
    group: bool,
    render: Render,
) -> tuple[str, EventDef]:
    return event_type, EventDef(event_type, title, description, recipients, group, render)


CATALOG: dict[str, EventDef] = dict(
    [
        _def("work_item.assigned", "Назначена работа", "Вам назначили работу в заказе",
             "target", False, _assigned),
        _def("work_item.updated", "Изменение по работе",
             "Изменён срок, добавлен комментарий или работа возвращена в исполнение",
             "target", False, _updated),
        _def("part_request.handled", "Ответ по заявке на запчасть",
             "Заявка одобрена, отклонена или выдана", "target", False, _part_handled),
        _def("appointment.created", "Новая запись", "Запись создана другим сотрудником",
             "location_managers_except_actor", False, _appt_created),
        _def("appointment.no_show", "Клиент не приехал", "Запись переведена в «Не явился»",
             "location_managers", True, _no_show),
        _def("work_item.finished", "Работа завершена", "Механик завершил работу в вашем заказе",
             "order_manager", False, _item_finished),
        _def("work_order.ready_for_check", "Заказ готов к проверке",
             "Все работы заказа выполнены", "order_manager", False, _ready_for_check),
        _def("part_request.created", "Заявка на запчасть", "Механик запросил запчасть",
             "location_managers", False, _part_created),
        _def("work_order.overdue", "Просроченный заказ", "Срок готовности заказа прошёл",
             "order_manager", True, _overdue),
        _def("stock.low", "Низкий остаток", "Остаток запчасти ниже минимума",
             "location_managers", True, _stock_low),
        _def("payment.refund", "Возврат оплаты", "Оформлен возврат по заказу",
             "directors", False, _refund),
        _def("order.discount_alert", "Крупная скидка", "Скидка в заказе выше порога",
             "directors", False, _discount),
        _def("user.locked", "Блокировка учётной записи",
             "Сотрудник заблокирован после неудачных входов", "directors", False, _locked),
        _def("report.daily_summary", "Ежедневная сводка", "Итоги дня по точкам",
             "directors", False, _daily),
    ]
)

# Порядок и состав событий в настройках по ролям (он же — значения по умолчанию).
ROLE_EVENTS: dict[str, tuple[str, ...]] = {
    "mechanic": ("work_item.assigned", "work_item.updated", "part_request.handled"),
    "manager": (
        "appointment.created",
        "appointment.no_show",
        "work_item.finished",
        "work_order.ready_for_check",
        "part_request.created",
        "work_order.overdue",
        "stock.low",
    ),
    "director": ("user.locked", "payment.refund", "order.discount_alert", "report.daily_summary"),
}
