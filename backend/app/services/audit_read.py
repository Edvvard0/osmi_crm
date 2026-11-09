"""Чтение журнала действий (только director): фильтры, метки и ссылки объектов, meta."""

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any, get_args
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import Select, column, func, select, table
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AuditLog, Location, User
from app.schemas.audit import (
    ActionOption,
    AuditAction,
    AuditEntry,
    AuditLocation,
    AuditMeta,
    AuditPage,
    EntityTypeOption,
    UserRef,
)
from app.services.audit import redact

log = structlog.get_logger()

ACTION_LABELS: dict[str, str] = {
    "create": "Создание",
    "update": "Изменение",
    "delete": "Удаление",
    "archive": "Архивация",
    "restore": "Восстановление",
    "status_change": "Смена статуса",
    "refund": "Возврат",
    "login": "Вход",
    "login_failed": "Неудачный вход",
    "logout": "Выход",
    "token_reuse": "Повторное использование токена",
    "password_change": "Смена пароля",
    "export": "Экспорт",
    "revoke_session": "Завершение сессии",
}

ENTITY_LABELS: dict[str, str] = {
    "user": "Сотрудник",
    "location": "Точка",
    "client": "Клиент",
    "vehicle": "Автомобиль",
    "service_category": "Категория услуг",
    "service": "Услуга",
    "part": "Запчасть",
    "post": "Пост",
    "service_price": "Цена услуги",
    "appointment": "Запись",
    "work_order": "Заказ-наряд",
    "work_order_item": "Работа в заказе",
    "work_order_part": "Запчасть в заказе",
    "work_order_comment": "Комментарий к заказу",
    "part_request": "Запрос запчастей",
    "vehicle_recommendation": "Рекомендация по автомобилю",
    "stock_balance": "Остаток на складе",
    "stock_receipt": "Приход на склад",
    "stock_transfer": "Перемещение между точками",
    "stock_inventory": "Инвентаризация",
    "stock_movement": "Движение по складу",
    "payment": "Платёж",
    "expense": "Расход",
    "expense_category": "Категория расходов",
    "payroll_scheme": "Схема оплаты труда",
    "payroll_adjustment": "Корректировка зарплаты",
    "report": "Отчёт",
    "payroll": "Зарплата",
    "system_settings": "Системные настройки",
    "session": "Сессия",
}

_ACTIONS = frozenset(get_args(AuditAction))

MAX_OFFSET = 10_000
MAX_DAYS = 366
DEFAULT_DAYS = 30


def audit_meta() -> AuditMeta:
    return AuditMeta(
        actions=[ActionOption(value=a, label=ACTION_LABELS[a]) for a in get_args(AuditAction)],
        entity_types=[EntityTypeOption(value=k, label=v) for k, v in ENTITY_LABELS.items()],
    )


def app_timezone() -> ZoneInfo:
    return ZoneInfo(getattr(get_settings(), "app_timezone", None) or "Europe/Moscow")


def _csv(raw: str | None, allowed: frozenset[str] | set[str], name: str) -> list[str] | None:
    if raw is None:
        return None
    values = [v.strip() for v in raw.split(",") if v.strip()]
    if any(v not in allowed for v in values):
        raise AppError(422, "validation_error", {name: "invalid_value"})
    return values or None


def _period(date_from: date | None, date_to: date | None, tz: ZoneInfo) -> tuple[datetime, datetime]:
    if date_to is None:
        date_to = datetime.now(tz).date()
    if date_from is None:
        date_from = date_to - timedelta(days=DEFAULT_DAYS - 1)
    if date_to < date_from or (date_to - date_from).days + 1 > MAX_DAYS:
        raise AppError(422, "validation_error", {"date_to": "invalid_period"})
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


# ---------- ссылки и метки объектов ----------

def _change_value(changes: dict[str, Any] | None, key: str) -> Any:
    """Значение ключа: простое или `new` из пары {old, new}."""
    if not changes or key not in changes:
        return None
    value = changes[key]
    if isinstance(value, dict) and "new" in value:
        value = value["new"]
    return value


def _change_uuid(changes: dict[str, Any] | None, key: str) -> str | None:
    value = _change_value(changes, key)
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _appointment_date(changes: dict[str, Any] | None, tz: ZoneInfo) -> str | None:
    for key in ("start_at", "date"):
        value = _change_value(changes, key)
        if isinstance(value, str):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                continue
            if moment.tzinfo is not None:
                moment = moment.astimezone(tz)
            return moment.date().isoformat()
    return None


_STATIC_PATHS = {
    "service_category": "/catalog",
    "service": "/catalog",
    "part": "/catalog",
    "post": "/catalog",
    "service_price": "/catalog",
    "stock_receipt": "/stock/movements",
    "stock_transfer": "/stock/movements",
    "stock_inventory": "/stock/movements",
    "stock_movement": "/stock/movements",
    "expense": "/cash",
    "expense_category": "/cash",
    "payroll_scheme": "/payroll",
    "payroll_adjustment": "/payroll",
    "system_settings": "/system-settings",
}
_OWN_PAGE = {
    "user": "/users",
    "location": "/locations",
    "client": "/clients",
    "vehicle": "/vehicles",
    "work_order": "/orders",
}
_ORDER_CHILDREN = {"work_order_item", "work_order_part", "work_order_comment", "part_request"}


def entity_path(
    entity_type: str,
    entity_id: uuid.UUID | None,
    changes: dict[str, Any] | None,
    tz: ZoneInfo,
) -> str | None:
    if entity_type in _OWN_PAGE:
        return f"{_OWN_PAGE[entity_type]}/{entity_id}" if entity_id else None
    if entity_type in _STATIC_PATHS:
        return _STATIC_PATHS[entity_type]
    if entity_type in _ORDER_CHILDREN:
        oid = _change_uuid(changes, "work_order_id")
        return f"/orders/{oid}" if oid else None
    if entity_type == "payment":
        oid = _change_uuid(changes, "order_id")
        return f"/orders/{oid}" if oid else None
    if entity_type == "vehicle_recommendation":
        vid = _change_uuid(changes, "vehicle_id")
        return f"/vehicles/{vid}" if vid else None
    if entity_type == "stock_balance":
        return f"/stock/{entity_id}" if entity_id else None
    if entity_type == "appointment":
        day = _appointment_date(changes, tz)
        return f"/calendar?date={day}" if day else "/calendar"
    return None  # report, payroll, session и неизвестные типы


# entity_type -> (таблица, колонка с меткой). Только имена без телефонов и госномеров.
_LABEL_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "user": ("users", ("full_name",)),
    "location": ("locations", ("name",)),
    "client": ("clients", ("full_name",)),
    "vehicle": ("vehicles", ("make", "model")),
    "service_category": ("service_categories", ("name",)),
    "service": ("services", ("name",)),
    "part": ("parts", ("name",)),
    "post": ("work_posts", ("name",)),
    "work_order": ("work_orders", ("number",)),
    "work_order_item": ("work_order_items", ("name",)),
    "work_order_part": ("work_order_parts", ("name",)),
    "expense_category": ("expense_categories", ("name",)),
    "stock_balance": ("parts", ("name",)),
}
# Типы, у которых пропажа объекта означает, что ссылка на страницу недействительна.
_LINK_NEEDS_OBJECT = {"user", "location", "client", "vehicle", "work_order"}


async def _labels(
    session: AsyncSession, entity_type: str, ids: set[uuid.UUID]
) -> dict[uuid.UUID, str] | None:
    """Метки объектов одного типа; None — источник недоступен (например, таблицы нет)."""
    source = _LABEL_SOURCES.get(entity_type)
    if source is None or not ids:
        return None
    tbl, cols = source
    t = table(tbl, column("id"), *(column(c) for c in cols))
    try:
        async with session.begin_nested():
            rows = (
                await session.execute(
                    select(t.c.id, *(t.c[c] for c in cols)).where(t.c.id.in_(list(ids)))
                )
            ).all()
    except DBAPIError:
        log.warning("audit_label_source_unavailable", entity_type=entity_type)
        return None
    return {r[0]: " ".join(str(v) for v in r[1:] if v is not None) for r in rows}


# ---------- список ----------


def _row_to_entry(
    row: Any,
    labels: dict[str, dict[uuid.UUID, str] | None],
) -> AuditEntry:
    log_row: AuditLog = row[0]
    entity_type = log_row.entity_type
    tz = ZoneInfo(row.tz) if row.tz else app_timezone()
    changes = redact(log_row.changes) if log_row.changes is not None else None
    label: str | None = None
    path = entity_path(entity_type, log_row.entity_id, changes, tz)
    found = labels.get(entity_type)
    if log_row.entity_id is not None and found is not None:
        label = found.get(log_row.entity_id)
        if label is None and entity_type in _LINK_NEEDS_OBJECT:
            path = None
    return AuditEntry(
        id=log_row.id,
        created_at=log_row.created_at,
        user=UserRef(id=row.user_id, full_name=row.user_name) if row.user_id else None,
        action=log_row.action,  # type: ignore[arg-type]
        entity_type=entity_type,
        entity_id=log_row.entity_id,
        entity_label=label,
        entity_path=path,
        location=(
            AuditLocation(id=row.loc_id, name=row.loc_name, timezone=row.tz) if row.loc_id else None
        ),
        changes=changes,
        ip=str(log_row.ip) if log_row.ip is not None else None,
        user_agent=log_row.user_agent,
    )


def _base_select() -> Select[Any]:
    return (
        select(
            AuditLog,
            User.id.label("user_id"),
            User.full_name.label("user_name"),
            Location.id.label("loc_id"),
            Location.name.label("loc_name"),
            Location.timezone.label("tz"),
        )
        .outerjoin(User, User.id == AuditLog.user_id)
        .outerjoin(Location, Location.id == AuditLog.location_id)
    )


async def _entries(session: AsyncSession, rows: list[Any]) -> list[AuditEntry]:
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for r in rows:
        log_row: AuditLog = r[0]
        if log_row.entity_id is not None:
            wanted[log_row.entity_type].add(log_row.entity_id)
    labels: dict[str, dict[uuid.UUID, str] | None] = {}
    for entity_type, ids in wanted.items():
        labels[entity_type] = await _labels(session, entity_type, ids)
    return [_row_to_entry(r, labels) for r in rows]


async def list_audit(
    session: AsyncSession,
    *,
    date_from: date | None,
    date_to: date | None,
    user_id: str | None,
    action: str | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> AuditPage:
    if offset > MAX_OFFSET:
        raise AppError(422, "validation_error", {"offset": "too_deep"})
    start, end = _period(date_from, date_to, app_timezone())
    actions = _csv(action, _ACTIONS, "action")
    types = _csv(entity_type, set(ENTITY_LABELS), "entity_type")
    conds: list[Any] = [AuditLog.created_at >= start, AuditLog.created_at < end]
    if user_id:
        if user_id == "system":
            conds.append(AuditLog.user_id.is_(None))
        else:
            try:
                conds.append(AuditLog.user_id == uuid.UUID(user_id))
            except ValueError:
                raise AppError(422, "validation_error", {"user_id": "invalid_value"}) from None
    if actions:
        conds.append(AuditLog.action.in_(actions))
    if types:
        conds.append(AuditLog.entity_type.in_(types))
    if entity_id is not None:
        conds.append(AuditLog.entity_id == entity_id)
    if location_id is not None:
        conds.append(AuditLog.location_id == location_id)
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    rows = (
        await session.execute(
            _base_select()
            .where(*conds)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return AuditPage(items=await _entries(session, list(rows)), total=total)


async def get_audit_entry(session: AsyncSession, entry_id: int) -> AuditEntry:
    if not 0 < entry_id < 2**63:
        raise AppError(404, "not_found")
    row = (await session.execute(_base_select().where(AuditLog.id == entry_id))).first()
    if row is None:
        raise AppError(404, "not_found")
    return (await _entries(session, [row]))[0]

