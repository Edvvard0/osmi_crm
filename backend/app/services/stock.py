"""Склад: остатки, движения, приход, списание, перемещение, инвентаризация, сторно."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import AppError
from app.models import Location, Part, Role, User
from app.models.stock import StockBalance, StockMovement
from app.schemas.stock import (
    InventoryCommit,
    InventoryOut,
    MinQuantityUpdate,
    MovementPage,
    MovementsOut,
    MovementType,
    PartBrief,
    PartMini,
    ReceiptCreate,
    ReverseCreate,
    StockBalanceRead,
    StockMovementRead,
    StockPage,
    StockTotals,
    TransferCreate,
    TransferOut,
    UserRef,
    WorkOrderRef,
    WriteOffCreate,
)
from app.services.audit import ClientInfo, diff, write_audit
from app.services.search import clean_term, contains
from app.services.stock_service import ZERO, Ledger, money, qty3

REVERSIBLE = frozenset({"receipt", "write_off", "adjustment"})
MANAGER_REVERSE_WINDOW = timedelta(days=7)
MAX_PERIOD_DAYS = 366

# Таблица заказов принадлежит модулю 5: берём только номер, без импорта модели.
_work_orders = sa.table("work_orders", sa.column("id", sa.Uuid()), sa.column("number", sa.String()))


# ---------------- вспомогательное ----------------


def _is_director(user: User) -> bool:
    return user.role == Role.director


async def _location(
    session: AsyncSession, location_id: uuid.UUID, allowed: list[uuid.UUID]
) -> Location:
    """Чужая и несуществующая точка неразличимы: оба случая — 404."""
    if location_id not in allowed:
        raise AppError(404, "not_found")
    loc = await session.get(Location, location_id)
    if loc is None:  # pragma: no cover - allowed строится из существующих точек
        raise AppError(404, "not_found")
    return loc


def _unique_parts(part_ids: list[uuid.UUID]) -> None:
    if len(set(part_ids)) != len(part_ids):
        raise AppError(422, "validation_error", {"items": "duplicate_part"})


async def _check_parts(
    session: AsyncSession, part_ids: list[uuid.UUID], *, active_only: bool
) -> None:
    _unique_parts(part_ids)
    stmt = select(Part.id).where(Part.id.in_(part_ids))
    if active_only:
        stmt = stmt.where(Part.is_active.is_(True))
    found = set(await session.scalars(stmt))
    if found != set(part_ids):
        raise AppError(422, "validation_error", {"items": "part_not_found"})


def _balance_read(
    part: Part, bal: StockBalance | None, location_id: uuid.UUID
) -> StockBalanceRead:
    quantity = bal.quantity if bal else ZERO
    minimum = bal.min_quantity if bal else ZERO
    avg = bal.avg_cost if bal else ZERO
    return StockBalanceRead(
        location_id=location_id,
        part=PartBrief.model_validate(part),
        quantity=quantity,
        min_quantity=minimum,
        avg_cost=avg,
        stock_value=money(quantity * avg),
        is_low=minimum > 0 and quantity < minimum,
        updated_at=bal.updated_at if bal else None,
    )


# ---------------- остатки ----------------

_SORTS = ("name", "sku", "quantity", "stock_value")


async def list_stock(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID,
    search: str | None,
    department: str | None,
    scope: str,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> StockPage:
    await _location(session, location_id, allowed)
    sb = StockBalance
    qty = func.coalesce(sb.quantity, 0)
    value = func.round(qty * func.coalesce(sb.avg_cost, 0), 2)
    low = and_(sb.min_quantity > 0, sb.quantity < sb.min_quantity)
    join_on = and_(sb.part_id == Part.id, sb.location_id == location_id)

    conds: list[ColumnElement[bool]] = []
    if scope == "stocked":
        conds.append(or_(sb.quantity > 0, sb.min_quantity > 0))
    elif scope == "low":
        conds.append(low)
    else:
        conds.append(Part.is_active.is_(True))
    if department:
        conds.append(Part.department == department)
    term = clean_term(search)
    if term:
        conds.append(
            contains(Part.name, term)
            | contains(Part.sku, term)
            | contains(Part.brand, term)
            | contains(Part.barcode, term)
        )

    agg = await session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((low, 1), else_=0)), 0),
            func.coalesce(func.sum(value), 0),
        )
        .select_from(Part)
        .outerjoin(sb, join_on)
        .where(*conds)
    )
    total, low_count, stock_value = agg.one()

    sort_col = {"name": Part.name, "sku": Part.sku, "quantity": qty, "stock_value": value}[sort]
    ordering: list[Any] = []
    if term:
        # Точное совпадение со штрихкодом — первым (сканер).
        ordering.append(case((Part.barcode == term, 0), else_=1))
    ordering += [sort_col.desc() if order == "desc" else sort_col.asc(), Part.id]
    rows = await session.execute(
        select(Part, sb)
        .outerjoin(sb, join_on)
        .where(*conds)
        .order_by(*ordering)
        .limit(limit)
        .offset(offset)
    )
    return StockPage(
        items=[_balance_read(part, bal, location_id) for part, bal in rows],
        total=total,
        totals=StockTotals(
            positions=total, low_count=int(low_count), stock_value=Decimal(stock_value)
        ),
    )


async def get_stock(
    session: AsyncSession, allowed: list[uuid.UUID], *, location_id: uuid.UUID, part_id: uuid.UUID
) -> StockBalanceRead:
    await _location(session, location_id, allowed)
    part = await session.get(Part, part_id)
    if part is None:
        raise AppError(404, "not_found")
    bal = await session.get(StockBalance, (location_id, part_id))
    return _balance_read(part, bal, location_id)


async def set_min_quantity(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID,
    part_id: uuid.UUID,
    data: MinQuantityUpdate,
    client: ClientInfo,
) -> StockBalanceRead:
    await _location(session, location_id, allowed)
    part = await session.get(Part, part_id)
    if part is None:
        raise AppError(404, "not_found")
    ledger = await Ledger.open(session, actor.id, [(location_id, part_id)])
    bal = ledger.balance(location_id, part_id)
    old = {"min_quantity": qty3(bal.min_quantity)}
    bal.min_quantity = data.min_quantity
    bal.updated_at = datetime.now(UTC)
    changes = diff(old, {"min_quantity": qty3(data.min_quantity)})
    write_audit(
        session,
        action="update",
        entity_type="stock_balance",
        user_id=actor.id,
        entity_id=part_id,
        location_id=location_id,
        changes=changes or None,
        client=client,
    )
    await session.flush()
    result = _balance_read(part, bal, location_id)
    await session.commit()
    return result


# ---------------- движения ----------------


def _movement_select() -> sa.Select[Any]:
    rev = aliased(StockMovement)
    reversed_expr = exists().where(
        rev.related_movement_id == StockMovement.id, rev.movement_type == "adjustment"
    )
    return (
        select(
            StockMovement,
            Part.sku,
            Part.name,
            Part.unit,
            User.full_name,
            _work_orders.c.number,
            reversed_expr.label("reversed"),
        )
        .join(Part, Part.id == StockMovement.part_id)
        .join(User, User.id == StockMovement.created_by)
        .outerjoin(_work_orders, _work_orders.c.id == StockMovement.work_order_id)
    )


def _movement_read(row: Any) -> StockMovementRead:
    m: StockMovement = row[0]
    return StockMovementRead(
        id=m.id,
        location_id=m.location_id,
        part=PartMini(id=m.part_id, sku=row[1], name=row[2], unit=row[3]),
        movement_type=m.movement_type,  # type: ignore[arg-type]
        quantity=m.quantity,
        unit_cost=m.unit_cost,
        total=money(m.quantity * m.unit_cost),
        balance_after=m.balance_after,
        work_order=(
            WorkOrderRef(id=m.work_order_id, number=row[5])
            if m.work_order_id is not None and row[5] is not None
            else None
        ),
        related_movement_id=m.related_movement_id,
        reversed=bool(row[6]),
        supplier=m.supplier,
        document_number=m.document_number,
        reason=m.reason,
        created_by=UserRef(id=m.created_by, full_name=row[4]),
        created_at=m.created_at,
    )


async def _read_movements(
    session: AsyncSession, movements: list[StockMovement]
) -> list[StockMovementRead]:
    if not movements:
        return []
    await session.flush()
    rows = await session.execute(
        _movement_select().where(StockMovement.id.in_([m.id for m in movements]))
    )
    by_id = {row[0].id: _movement_read(row) for row in rows}
    return [by_id[m.id] for m in movements]


async def list_movements(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID,
    part_id: uuid.UUID | None,
    movement_type: MovementType | None,
    work_order_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> MovementPage:
    loc = await _location(session, location_id, allowed)
    if date_from and date_to:
        if date_to < date_from:
            raise AppError(422, "validation_error", {"date_to": "before_date_from"})
        if (date_to - date_from).days + 1 > MAX_PERIOD_DAYS:
            raise AppError(422, "validation_error", {"date_to": "period_too_long"})
    tz = ZoneInfo(loc.timezone)
    conds: list[ColumnElement[bool]] = [StockMovement.location_id == location_id]
    if part_id:
        conds.append(StockMovement.part_id == part_id)
    if movement_type:
        conds.append(StockMovement.movement_type == movement_type)
    if work_order_id:
        conds.append(StockMovement.work_order_id == work_order_id)
    if date_from:
        conds.append(StockMovement.created_at >= datetime.combine(date_from, time.min, tz))
    if date_to:
        conds.append(
            StockMovement.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tz)
        )
    total = (
        await session.scalar(select(func.count()).select_from(StockMovement).where(*conds)) or 0
    )
    rows = await session.execute(
        _movement_select()
        .where(*conds)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return MovementPage(items=[_movement_read(r) for r in rows], total=total)


# ---------------- приход ----------------


async def create_receipt(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    data: ReceiptCreate,
    client: ClientInfo,
) -> MovementsOut:
    await _location(session, data.location_id, allowed)
    part_ids = [i.part_id for i in data.items]
    await _check_parts(session, part_ids, active_only=True)
    ledger = await Ledger.open(session, actor.id, [(data.location_id, p) for p in part_ids])
    movements = [
        await ledger.post(
            location_id=data.location_id,
            part_id=item.part_id,
            movement_type="receipt",
            quantity=item.quantity,
            unit_cost=item.unit_cost,
            supplier=data.supplier or None,
            document_number=data.document_number or None,
        )
        for item in data.items
    ]
    write_audit(
        session,
        action="create",
        entity_type="stock_receipt",
        user_id=actor.id,
        entity_id=movements[0].id,
        location_id=data.location_id,
        changes={"items": len(movements), "document_number": data.document_number or None},
        client=client,
    )
    out = await _read_movements(session, movements)
    await session.commit()
    return MovementsOut(movements=out)


# ---------------- списание ----------------


async def create_write_off(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    data: WriteOffCreate,
    client: ClientInfo,
) -> MovementsOut:
    await _location(session, data.location_id, allowed)
    part_ids = [i.part_id for i in data.items]
    await _check_parts(session, part_ids, active_only=False)
    ledger = await Ledger.open(session, actor.id, [(data.location_id, p) for p in part_ids])
    movements = [
        await ledger.post(
            location_id=data.location_id,
            part_id=item.part_id,
            movement_type="write_off",
            quantity=-item.quantity,
            reason=data.reason,
        )
        for item in data.items
    ]
    for m in movements:
        write_audit(
            session,
            action="create",
            entity_type="stock_movement",
            user_id=actor.id,
            entity_id=m.id,
            location_id=data.location_id,
            changes={
                "movement_type": "write_off",
                "part_id": str(m.part_id),
                "quantity": qty3(m.quantity),
                "reason": data.reason,
            },
            client=client,
        )
    out = await _read_movements(session, movements)
    await session.commit()
    return MovementsOut(movements=out)


# ---------------- перемещение ----------------


async def create_transfer(
    session: AsyncSession, actor: User, data: TransferCreate, client: ClientInfo
) -> TransferOut:
    if data.from_location_id == data.to_location_id:
        raise AppError(422, "validation_error", {"to_location_id": "same_location"})
    fields: dict[str, str] = {}
    for name, loc_id in (
        ("from_location_id", data.from_location_id),
        ("to_location_id", data.to_location_id),
    ):
        loc = await session.get(Location, loc_id)
        if loc is None or not loc.is_active:
            fields[name] = "location_unavailable"
    if fields:
        raise AppError(422, "validation_error", fields)
    part_ids = [i.part_id for i in data.items]
    await _check_parts(session, part_ids, active_only=False)
    keys = [(data.from_location_id, p) for p in part_ids] + [
        (data.to_location_id, p) for p in part_ids
    ]
    ledger = await Ledger.open(session, actor.id, keys)
    outs: list[StockMovement] = []
    ins: list[StockMovement] = []
    for item in data.items:
        out = await ledger.post(
            location_id=data.from_location_id,
            part_id=item.part_id,
            movement_type="transfer_out",
            quantity=-item.quantity,
            reason=data.comment,
        )
        outs.append(out)
        ins.append(
            await ledger.post(
                location_id=data.to_location_id,
                part_id=item.part_id,
                movement_type="transfer_in",
                quantity=item.quantity,
                unit_cost=out.unit_cost,
                related_movement_id=out.id,
                reason=data.comment,
            )
        )
        await session.flush()  # FK in -> out: порядок вставки
    write_audit(
        session,
        action="create",
        entity_type="stock_transfer",
        user_id=actor.id,
        entity_id=outs[0].id,
        location_id=data.from_location_id,
        changes={"to_location_id": str(data.to_location_id), "items": len(outs)},
        client=client,
    )
    out_read = await _read_movements(session, outs)
    in_read = await _read_movements(session, ins)
    await session.commit()
    return TransferOut(out=out_read, **{"in": in_read})


# ---------------- инвентаризация ----------------


async def commit_inventory(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    data: InventoryCommit,
    client: ClientInfo,
) -> InventoryOut:
    await _location(session, data.location_id, allowed)
    part_ids = [i.part_id for i in data.items]
    await _check_parts(session, part_ids, active_only=False)
    ledger = await Ledger.open(session, actor.id, [(data.location_id, p) for p in part_ids])
    for item in data.items:
        if ledger.balance(data.location_id, item.part_id).quantity != item.expected_quantity:
            raise AppError(
                409, "stock_changed", details={"part_id": str(item.part_id)}
            )
    reason = data.comment or "Инвентаризация"
    movements: list[StockMovement] = []
    skipped = 0
    for item in data.items:
        current = ledger.balance(data.location_id, item.part_id).quantity
        if item.actual_quantity == current:
            skipped += 1
            continue
        movements.append(
            await ledger.post(
                location_id=data.location_id,
                part_id=item.part_id,
                movement_type="adjustment",
                quantity=item.actual_quantity - current,
                reason=reason,
            )
        )
    write_audit(
        session,
        action="create",
        entity_type="stock_inventory",
        user_id=actor.id,
        entity_id=movements[0].id if movements else None,
        location_id=data.location_id,
        changes={"adjusted": len(movements), "skipped": skipped},
        client=client,
    )
    out = await _read_movements(session, movements)
    await session.commit()
    return InventoryOut(movements=out, skipped=skipped)


# ---------------- сторно ----------------


async def reverse_movement(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    movement_id: uuid.UUID,
    data: ReverseCreate,
    client: ClientInfo,
) -> StockMovementRead:
    original = await session.get(StockMovement, movement_id)
    if original is None or original.location_id not in allowed:
        raise AppError(404, "not_found")
    if original.movement_type not in REVERSIBLE:
        raise AppError(409, "invalid_state")
    if (
        not _is_director(actor)
        and datetime.now(UTC) - original.created_at > MANAGER_REVERSE_WINDOW
    ):
        raise AppError(403, "forbidden")
    # Блокировка строки остатка сериализует сторно одной позиции (UPDATE на движения отозван).
    ledger = await Ledger.open(session, actor.id, [(original.location_id, original.part_id)])
    already = await session.scalar(
        select(StockMovement.id).where(
            StockMovement.related_movement_id == original.id,
            StockMovement.movement_type == "adjustment",
        )
    )
    if already is not None:
        raise AppError(409, "already_reversed")
    movement = await ledger.post(
        location_id=original.location_id,
        part_id=original.part_id,
        movement_type="adjustment",
        quantity=-original.quantity,
        unit_cost=original.unit_cost,
        related_movement_id=original.id,
        reason=data.reason,
    )
    write_audit(
        session,
        action="create",
        entity_type="stock_movement",
        user_id=actor.id,
        entity_id=movement.id,
        location_id=original.location_id,
        changes={
            "movement_type": "adjustment",
            "reversal_of": str(original.id),
            "quantity": qty3(movement.quantity),
            "reason": data.reason,
        },
        client=client,
    )
    out = (await _read_movements(session, [movement]))[0]
    await session.commit()
    return out
