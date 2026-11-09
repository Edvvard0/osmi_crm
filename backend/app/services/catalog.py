"""Каталог: категории, услуги, цены по точкам, посты, запчасти."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    Location,
    Part,
    Role,
    Service,
    ServiceCategory,
    ServiceLocationPrice,
    User,
    WorkPost,
)
from app.schemas.catalog import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    PartCreate,
    PartPage,
    PartRead,
    PartUpdate,
    PostCreate,
    PostRead,
    PostUpdate,
    ServiceCreate,
    ServicePage,
    ServicePriceRead,
    ServiceRead,
    ServiceUpdate,
)
from app.services.audit import ClientInfo, diff, write_audit
from app.services.search import clean_term, contains

_CATEGORY_FIELDS = ("name", "sort_order", "is_active")
_SERVICE_FIELDS = (
    "category_id", "code", "name", "description", "department", "unit", "base_price",
    "norm_hours", "duration_minutes", "is_active",
)  # fmt: skip
_POST_FIELDS = ("name", "post_type", "department", "sort_order", "is_active")
_PART_FIELDS = (
    "sku", "name", "brand", "barcode", "unit", "department", "sale_price", "is_active",
)  # fmt: skip


def _snapshot(obj: object, fields: tuple[str, ...]) -> dict[str, Any]:
    """Снимок для журнала: Decimal и UUID приводятся к строкам (JSON)."""
    snap: dict[str, Any] = {}
    for f in fields:
        v = getattr(obj, f)
        if isinstance(v, Decimal):
            v = f"{v:.2f}"
        elif isinstance(v, uuid.UUID):
            v = str(v)
        snap[f] = v
    return snap


def _normalize(values: dict[str, Any]) -> dict[str, Any]:
    """Пустая строка после очистки (например, из одного NUL) означает «нет значения»."""
    return {k: (None if isinstance(v, str) and v == "" else v) for k, v in values.items()}


def _created(
    session: AsyncSession,
    actor: User,
    entity_type: str,
    obj: Any,
    fields: tuple[str, ...],
    client: ClientInfo,
    location_id: uuid.UUID | None = None,
) -> None:
    write_audit(
        session,
        action="create",
        entity_type=entity_type,
        user_id=actor.id,
        entity_id=obj.id,
        location_id=location_id,
        changes={k: {"old": None, "new": v} for k, v in _snapshot(obj, fields).items()},
        client=client,
    )


def _updated(
    session: AsyncSession,
    actor: User,
    entity_type: str,
    obj: Any,
    old: dict[str, Any],
    fields: tuple[str, ...],
    client: ClientInfo,
    location_id: uuid.UUID | None = None,
) -> None:
    changes = diff(old, _snapshot(obj, fields))
    if changes:
        write_audit(
            session,
            action="update",
            entity_type=entity_type,
            user_id=actor.id,
            entity_id=obj.id,
            location_id=location_id,
            changes=changes,
            client=client,
        )


# ---------------- категории ----------------


async def list_categories(
    session: AsyncSession, *, department: str | None, is_active: bool | None
) -> list[CategoryRead]:
    stmt = select(ServiceCategory)
    if department:
        stmt = stmt.where(ServiceCategory.department == department)
    if is_active is not None:
        stmt = stmt.where(ServiceCategory.is_active == is_active)
    rows = await session.scalars(
        stmt.order_by(
            ServiceCategory.department,
            ServiceCategory.sort_order,
            ServiceCategory.name,
            ServiceCategory.id,
        )
    )
    return [CategoryRead.model_validate(r) for r in rows]


async def create_category(
    session: AsyncSession, actor: User, data: CategoryCreate, client: ClientInfo
) -> CategoryRead:
    cat = ServiceCategory(**data.model_dump())
    session.add(cat)
    await session.flush()
    _created(session, actor, "service_category", cat, _CATEGORY_FIELDS, client)
    await session.commit()
    return CategoryRead.model_validate(cat)


async def update_category(
    session: AsyncSession,
    actor: User,
    category_id: uuid.UUID,
    data: CategoryUpdate,
    client: ClientInfo,
) -> CategoryRead:
    cat = await session.get(ServiceCategory, category_id, with_for_update=True)
    if cat is None:
        raise AppError(404, "not_found")
    old = _snapshot(cat, _CATEGORY_FIELDS)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(cat, field, value)
    _updated(session, actor, "service_category", cat, old, _CATEGORY_FIELDS, client)
    await session.commit()
    return CategoryRead.model_validate(cat)


# ---------------- услуги ----------------


def _service_read(service: Service, price: Decimal | None = None) -> ServiceRead:
    return ServiceRead(
        id=service.id,
        category_id=service.category_id,
        code=service.code,
        name=service.name,
        description=service.description,
        department=service.department,
        unit=service.unit,
        base_price=service.base_price,
        norm_hours=service.norm_hours,
        duration_minutes=service.duration_minutes,
        is_active=service.is_active,
        price=service.base_price if price is None else price,
    )


def resolve_price_location(
    user: User, location_id: uuid.UUID | None, allowed: list[uuid.UUID]
) -> uuid.UUID | None:
    """Точка для эффективной цены. Менеджер обязан указать свою (иначе 422); чужая — 404."""
    if location_id is None:
        if user.role != Role.director:
            raise AppError(422, "validation_error", {"location_id": "missing"})
        return None
    if location_id not in allowed:
        raise AppError(404, "not_found")
    return location_id


async def list_services(
    session: AsyncSession,
    *,
    search: str | None,
    category_id: uuid.UUID | None,
    department: str | None,
    is_active: bool | None,
    location_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> ServicePage:
    conds: list[ColumnElement[bool]] = []
    term = clean_term(search)
    if term:
        conds.append(contains(Service.name, term) | contains(Service.code, term))
    if category_id:
        conds.append(Service.category_id == category_id)
    if department:
        conds.append(Service.department == department)
    if is_active is not None:
        conds.append(Service.is_active == is_active)
    total = await session.scalar(select(func.count()).select_from(Service).where(*conds)) or 0
    stmt = select(Service, ServiceLocationPrice.price)
    # Без точки соединение заведомо пустое: price = NULL → берётся базовая цена.
    stmt = stmt.outerjoin(
        ServiceLocationPrice,
        (ServiceLocationPrice.service_id == Service.id)
        & (
            ServiceLocationPrice.location_id == location_id
            if location_id is not None
            else ServiceLocationPrice.location_id.is_(None)
        ),
    )
    rows = (
        await session.execute(
            stmt.where(*conds).order_by(Service.code, Service.id).limit(limit).offset(offset)
        )
    ).all()
    return ServicePage(items=[_service_read(s, p) for s, p in rows], total=total)


async def get_service(
    session: AsyncSession, service_id: uuid.UUID, *, for_update: bool = False
) -> Service:
    service = await session.get(Service, service_id, with_for_update=for_update)
    if service is None:
        raise AppError(404, "not_found")
    return service


async def get_service_read(
    session: AsyncSession, service_id: uuid.UUID, location_id: uuid.UUID | None
) -> ServiceRead:
    service = await get_service(session, service_id)
    price: Decimal | None = None
    if location_id is not None:
        price = await session.scalar(
            select(ServiceLocationPrice.price).where(
                ServiceLocationPrice.service_id == service_id,
                ServiceLocationPrice.location_id == location_id,
            )
        )
    return _service_read(service, price)


async def create_service(
    session: AsyncSession, actor: User, data: ServiceCreate, client: ClientInfo
) -> ServiceRead:
    category = await session.get(ServiceCategory, data.category_id)
    if category is None:
        raise AppError(422, "validation_error", {"category_id": "not_found"})
    values = _normalize(data.model_dump())
    if values["norm_hours"] is None:
        values["norm_hours"] = Decimal(0)
    service = Service(**values, department=category.department)
    session.add(service)
    await session.flush()
    _created(session, actor, "service", service, _SERVICE_FIELDS, client)
    await session.commit()
    return _service_read(service)


async def update_service(
    session: AsyncSession,
    actor: User,
    service_id: uuid.UUID,
    data: ServiceUpdate,
    client: ClientInfo,
) -> ServiceRead:
    service = await get_service(session, service_id, for_update=True)
    values = _normalize(data.model_dump(exclude_unset=True))
    if "norm_hours" in values and values["norm_hours"] is None:
        values["norm_hours"] = Decimal(0)
    old = _snapshot(service, _SERVICE_FIELDS)
    for field, value in values.items():
        setattr(service, field, value)
    _updated(session, actor, "service", service, old, _SERVICE_FIELDS, client)
    await session.commit()
    return _service_read(service)


# ---------------- цены по точкам ----------------


async def _ensure_location(session: AsyncSession, location_id: uuid.UUID) -> None:
    if await session.get(Location, location_id) is None:
        raise AppError(404, "not_found")


async def list_location_prices(
    session: AsyncSession, location_id: uuid.UUID
) -> list[ServicePriceRead]:
    await _ensure_location(session, location_id)
    rows = await session.scalars(
        select(ServiceLocationPrice)
        .where(ServiceLocationPrice.location_id == location_id)
        .order_by(ServiceLocationPrice.service_id)
    )
    return [ServicePriceRead.model_validate(r) for r in rows]


async def list_service_prices(
    session: AsyncSession, service_id: uuid.UUID
) -> list[ServicePriceRead]:
    await get_service(session, service_id)
    rows = await session.scalars(
        select(ServiceLocationPrice)
        .where(ServiceLocationPrice.service_id == service_id)
        .order_by(ServiceLocationPrice.location_id)
    )
    return [ServicePriceRead.model_validate(r) for r in rows]


async def set_price(
    session: AsyncSession,
    actor: User,
    service_id: uuid.UUID,
    location_id: uuid.UUID,
    price: Decimal,
    client: ClientInfo,
) -> ServicePriceRead:
    await get_service(session, service_id)
    await _ensure_location(session, location_id)
    row = await session.get(ServiceLocationPrice, (service_id, location_id), with_for_update=True)
    old = None if row is None else f"{row.price:.2f}"
    if row is None:
        row = ServiceLocationPrice(service_id=service_id, location_id=location_id, price=price)
        session.add(row)
    else:
        row.price = price
    await session.flush()
    new = f"{price:.2f}"
    if old != new:
        write_audit(
            session,
            action="create" if old is None else "update",
            entity_type="service_price",
            user_id=actor.id,
            entity_id=service_id,
            location_id=location_id,
            changes={"price": {"old": old, "new": new}},
            client=client,
        )
    await session.commit()
    await session.refresh(row)  # updated_at выставляет БД
    return ServicePriceRead.model_validate(row)


async def delete_price(
    session: AsyncSession,
    actor: User,
    service_id: uuid.UUID,
    location_id: uuid.UUID,
    client: ClientInfo,
) -> None:
    """Возврат к базовой цене. Идемпотентно: если переопределения нет — тоже 204."""
    await get_service(session, service_id)
    await _ensure_location(session, location_id)
    row = await session.get(ServiceLocationPrice, (service_id, location_id), with_for_update=True)
    if row is not None:
        write_audit(
            session,
            action="delete",
            entity_type="service_price",
            user_id=actor.id,
            entity_id=service_id,
            location_id=location_id,
            changes={"price": {"old": f"{row.price:.2f}", "new": None}},
            client=client,
        )
        await session.delete(row)
    await session.commit()


# ---------------- посты ----------------


def _ensure_allowed(location_id: uuid.UUID, allowed: list[uuid.UUID]) -> None:
    """Чужая и несуществующая точка неразличимы: оба случая — 404."""
    if location_id not in allowed:
        raise AppError(404, "not_found")


async def list_posts(
    session: AsyncSession,
    location_id: uuid.UUID,
    allowed: list[uuid.UUID],
    *,
    is_active: bool | None,
) -> list[PostRead]:
    _ensure_allowed(location_id, allowed)
    stmt = select(WorkPost).where(WorkPost.location_id == location_id)
    if is_active is not None:
        stmt = stmt.where(WorkPost.is_active == is_active)
    rows = await session.scalars(stmt.order_by(WorkPost.sort_order, WorkPost.name, WorkPost.id))
    return [PostRead.model_validate(r) for r in rows]


async def create_post(
    session: AsyncSession,
    actor: User,
    location_id: uuid.UUID,
    allowed: list[uuid.UUID],
    data: PostCreate,
    client: ClientInfo,
) -> PostRead:
    _ensure_allowed(location_id, allowed)
    post = WorkPost(**data.model_dump(), location_id=location_id)
    session.add(post)
    await session.flush()
    _created(session, actor, "work_post", post, _POST_FIELDS, client, location_id)
    await session.commit()
    return PostRead.model_validate(post)


async def update_post(
    session: AsyncSession,
    actor: User,
    post_id: uuid.UUID,
    data: PostUpdate,
    client: ClientInfo,
) -> PostRead:
    post = await session.get(WorkPost, post_id, with_for_update=True)
    if post is None:
        raise AppError(404, "not_found")
    old = _snapshot(post, _POST_FIELDS)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(post, field, value)
    _updated(session, actor, "work_post", post, old, _POST_FIELDS, client, post.location_id)
    await session.commit()
    return PostRead.model_validate(post)


# ---------------- запчасти ----------------


async def list_parts(
    session: AsyncSession,
    *,
    search: str | None,
    department: str | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> PartPage:
    conds: list[ColumnElement[bool]] = []
    term = clean_term(search)
    if term:
        conds.append(
            contains(Part.name, term)
            | contains(Part.sku, term)
            | contains(Part.brand, term)
            | contains(Part.barcode, term)
        )
    if department:
        conds.append(Part.department == department)
    if is_active is not None:
        conds.append(Part.is_active == is_active)
    total = await session.scalar(select(func.count()).select_from(Part).where(*conds)) or 0
    rows = await session.scalars(
        select(Part).where(*conds).order_by(Part.name, Part.id).limit(limit).offset(offset)
    )
    return PartPage(items=[PartRead.model_validate(r) for r in rows], total=total)


async def create_part(
    session: AsyncSession, actor: User, data: PartCreate, client: ClientInfo
) -> PartRead:
    part = Part(**_normalize(data.model_dump()))
    session.add(part)
    await session.flush()
    _created(session, actor, "part", part, _PART_FIELDS, client)
    await session.commit()
    return PartRead.model_validate(part)


async def update_part(
    session: AsyncSession,
    actor: User,
    part_id: uuid.UUID,
    data: PartUpdate,
    client: ClientInfo,
) -> PartRead:
    part = await session.get(Part, part_id, with_for_update=True)
    if part is None:
        raise AppError(404, "not_found")
    old = _snapshot(part, _PART_FIELDS)
    for field, value in _normalize(data.model_dump(exclude_unset=True)).items():
        setattr(part, field, value)
    _updated(session, actor, "part", part, old, _PART_FIELDS, client)
    await session.commit()
    return PartRead.model_validate(part)
