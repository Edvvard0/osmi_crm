"""Поиск по клиентам и автомобилям: ILIKE по триграммным индексам, параметризованно."""

import re

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.types import _CTRL, _LAT2CYR
from app.models import Client, Vehicle
from app.schemas.client import SearchHit

_CYR_UP = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
_CYR_LOW = _CYR_UP.lower()
_PHONE_LIKE = re.compile(r"^[\d\s()+\-.]+$")


def clean_term(raw: str | None) -> str:
    """Убирает управляющие символы (в т.ч. NUL) и невалидный UTF-8; обрезает пробелы."""
    s = (raw or "").encode("utf-8", "ignore").decode("utf-8")
    return _CTRL.sub("", s).strip()


def like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _pattern(value: str) -> str:
    return f"%{like_escape(value)}%"


def _fold(column: ColumnElement[str] | InstrumentedAttribute[str | None]) -> ColumnElement[str]:
    """Сворачивает регистр кириллицы независимо от локали БД (в C-локали ILIKE не умеет)."""
    return func.translate(column, _CYR_UP, _CYR_LOW)


def _ilike(column: InstrumentedAttribute[str | None], value: str) -> ColumnElement[bool]:
    return _fold(column).ilike(_pattern(value.lower()), escape="\\")


def contains(column: InstrumentedAttribute[str | None], value: str) -> ColumnElement[bool]:
    """Подстрока без учёта регистра (в т.ч. кириллицы); % и _ в запросе — обычные символы."""
    return _ilike(column, value)


def phone_digits(term: str) -> str | None:
    """Если запрос похож на телефон — только цифры (8XXXXXXXXXX → 7XXXXXXXXXX), иначе None."""
    if not _PHONE_LIKE.fullmatch(term):
        return None
    digits = re.sub(r"\D", "", term)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits or None


def vehicle_cond(term: str, *, with_make_model: bool = False) -> ColumnElement[bool]:
    """Госномер (любой регистр, кириллица/латиница), VIN (часть), по желанию марка/модель."""
    compact = re.sub(r"\s", "", term).upper()
    conds: list[ColumnElement[bool]] = []
    if compact:
        conds.append(Vehicle.plate_number.ilike(_pattern(compact.translate(_LAT2CYR)), escape="\\"))
        conds.append(Vehicle.vin.ilike(_pattern(compact), escape="\\"))
    if with_make_model:
        conds.append(_ilike(Vehicle.make, term))
        conds.append(_ilike(Vehicle.model, term))
    return or_(*conds)


def client_cond(term: str) -> ColumnElement[bool]:
    """ФИО, компания, телефон (в т.ч. последние цифры), госномер/VIN автомобилей клиента."""
    conds: list[ColumnElement[bool]] = [
        _ilike(Client.full_name, term),
        _ilike(Client.company_name, term),
        exists().where(
            and_(
                Vehicle.client_id == Client.id,
                Vehicle.archived_at.is_(None),
                vehicle_cond(term),
            )
        ),
    ]
    digits = phone_digits(term)
    if digits:
        conds.append(Client.phone.ilike(_pattern(digits), escape="\\"))
        conds.append(Client.phone_extra.ilike(_pattern(digits), escape="\\"))
    return or_(*conds)


async def global_search(session: AsyncSession, term: str, limit: int) -> list[SearchHit]:
    clients = (
        await session.scalars(
            select(Client)
            .where(Client.archived_at.is_(None), client_cond(term))
            .order_by(Client.full_name, Client.id)
            .limit(limit)
        )
    ).all()
    vehicles = (
        await session.scalars(
            select(Vehicle)
            .where(Vehicle.archived_at.is_(None), vehicle_cond(term, with_make_model=True))
            .order_by(Vehicle.make, Vehicle.model, Vehicle.id)
            .limit(limit)
        )
    ).all()
    hits_c = [
        SearchHit(type="client", id=c.id, title=c.full_name, subtitle=c.phone, client_id=c.id)
        for c in clients
    ]
    hits_v = [
        SearchHit(
            type="vehicle",
            id=v.id,
            title=f"{v.make} {v.model}",
            subtitle=v.plate_number or v.vin or "",
            client_id=v.client_id,
        )
        for v in vehicles
    ]
    # Поровну клиентов и авто; если одних меньше, остаток добирают другими.
    out: list[SearchHit] = []
    ci = vi = 0
    while len(out) < limit and (ci < len(hits_c) or vi < len(hits_v)):
        if ci < len(hits_c):
            out.append(hits_c[ci])
            ci += 1
        if len(out) < limit and vi < len(hits_v):
            out.append(hits_v[vi])
            vi += 1
    return out
