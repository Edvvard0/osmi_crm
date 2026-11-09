"""Заявки на запчасти (модуль 6): создание механиком, обработка менеджером и директором."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import AppError
from app.models import Part, User, Vehicle
from app.models.mechanic import PartRequest
from app.models.work_order import WorkOrder, WorkOrderItem
from app.schemas.mechanic import (
    OrderBrief,
    PartApproveBody,
    PartBrief,
    PartFull,
    PartIssueBody,
    PartIssueResult,
    PartRejectBody,
    PartRequestCreate,
    PartRequestFull,
    PartRequestFullPage,
    PartRequestPage,
    PartRequestRead,
    PartRequestSummary,
    UserRef,
    VehicleRef,
)
from app.schemas.work_order import PartCreate
from app.services import events, stock_service, timers, work_orders
from app.services.audit import ClientInfo, write_audit
from app.services.mechanic import load_item

CLOSED = ("closed", "cancelled")
BLOCKED_FOR_CREATE = ("ready", "closed", "cancelled")


def _unprocessable(**fields: str) -> AppError:
    return AppError(422, "validation_error", fields)


def _audit_status(
    session: AsyncSession,
    actor: User,
    req: PartRequest,
    order: WorkOrder,
    changes: dict[str, object],
    client: ClientInfo,
) -> None:
    write_audit(
        session,
        action="status_change",
        entity_type="part_request",
        entity_id=req.id,
        location_id=order.location_id,
        user_id=actor.id,
        changes=changes,
        client=client,
    )


# ---------------- механик ----------------


def _mechanic_read(
    req: PartRequest, order: WorkOrder, item: WorkOrderItem | None, part: Part | None
) -> PartRequestRead:
    return PartRequestRead(
        id=req.id,
        order_id=order.id,
        order_number=order.number,
        item_id=req.item_id,
        item_name=item.name if item else None,
        part=PartBrief(id=part.id, name=part.name, sku=part.sku) if part else None,
        description=req.description,
        quantity=req.quantity,
        unit=part.unit if part else None,
        status=req.status,
        reject_reason=req.reject_reason,
        created_at=req.created_at,
        handled_at=req.handled_at,
    )


async def create_for_mechanic(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    data: PartRequestCreate,
    client: ClientInfo,
) -> PartRequestRead:
    item, order = await load_item(session, user, allowed, data.item_id)
    part: Part | None = None
    if data.part_id is not None:
        part = await session.get(Part, data.part_id)
        if part is None or not part.is_active:
            raise _unprocessable(part_id="invalid")
    description = data.description or (part.name if part else None)
    if not description:
        raise _unprocessable(description="required")
    if order.status in BLOCKED_FOR_CREATE:
        raise AppError(409, "invalid_state")
    req = PartRequest(
        work_order_id=order.id,
        item_id=item.id,
        mechanic_id=user.id,
        part_id=part.id if part else None,
        description=description[:500],
        quantity=data.quantity,
        status="new",
        created_at=timers.now(),
    )
    session.add(req)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="part_request",
        entity_id=req.id,
        location_id=order.location_id,
        user_id=user.id,
        changes={
            "work_order_id": str(order.id),
            "item_id": str(item.id),
            "part_id": str(part.id) if part else None,
            "description": req.description,
            "quantity": f"{req.quantity:.3f}",
        },
        client=client,
    )
    await events.publish(
        session,
        "part_request.created",
        {
            "request_id": str(req.id),
            "order_number": order.number,
            "description": req.description,
            "quantity": f"{req.quantity:.3f}",
            "mechanic_name": user.full_name,
        },
        location_id=order.location_id,
        actor_id=user.id,
    )
    await session.commit()
    return _mechanic_read(req, order, item, part)


async def list_for_mechanic(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    status: str | None,
    limit: int,
    offset: int,
) -> PartRequestPage:
    conds: list[ColumnElement[bool]] = [
        PartRequest.mechanic_id == user.id,
        WorkOrder.location_id.in_(allowed),
    ]
    if status is not None:
        conds.append(PartRequest.status == status)
    total = await session.scalar(
        select(func.count())
        .select_from(PartRequest)
        .join(WorkOrder, WorkOrder.id == PartRequest.work_order_id)
        .where(*conds)
    )
    rows = (
        await session.execute(
            select(PartRequest, WorkOrder, WorkOrderItem, Part)
            .join(WorkOrder, WorkOrder.id == PartRequest.work_order_id)
            .outerjoin(WorkOrderItem, WorkOrderItem.id == PartRequest.item_id)
            .outerjoin(Part, Part.id == PartRequest.part_id)
            .where(*conds)
            .order_by(PartRequest.created_at.desc(), PartRequest.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return PartRequestPage(
        items=[_mechanic_read(r, o, i, p) for r, o, i, p in rows], total=total or 0
    )


# ---------------- менеджер / директор ----------------


async def _in_stock(
    session: AsyncSession, pairs: Sequence[tuple[uuid.UUID, uuid.UUID]]
) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
    """Остатки (точка, запчасть): один запрос на точку."""
    by_location: dict[uuid.UUID, set[uuid.UUID]] = {}
    for loc, part in pairs:
        by_location.setdefault(loc, set()).add(part)
    result: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    for loc, parts in by_location.items():
        stock = await stock_service.stock_for_parts(session, location_id=loc, part_ids=parts)
        result.update({(loc, pid): qty for pid, qty in stock.items()})
    return result


async def _full_reads(session: AsyncSession, ids: Sequence[uuid.UUID]) -> list[PartRequestFull]:
    """Полные карточки в порядке `ids`."""
    if not ids:
        return []
    mech, handler = aliased(User), aliased(User)
    rows = (
        await session.execute(
            select(PartRequest, WorkOrder, Vehicle, WorkOrderItem, mech, Part, handler)
            .join(WorkOrder, WorkOrder.id == PartRequest.work_order_id)
            .join(Vehicle, Vehicle.id == WorkOrder.vehicle_id)
            .outerjoin(WorkOrderItem, WorkOrderItem.id == PartRequest.item_id)
            .join(mech, mech.id == PartRequest.mechanic_id)
            .outerjoin(Part, Part.id == PartRequest.part_id)
            .outerjoin(handler, handler.id == PartRequest.handled_by)
            .where(PartRequest.id.in_(list(ids)))
            .execution_options(populate_existing=True)
        )
    ).all()
    stock = await _in_stock(
        session, [(o.location_id, p.id) for _, o, _, _, _, p, _ in rows if p is not None]
    )
    by_id: dict[uuid.UUID, PartRequestFull] = {}
    for req, order, vehicle, item, m, part, h in rows:
        by_id[req.id] = PartRequestFull(
            id=req.id,
            location_id=order.location_id,
            order=OrderBrief(
                id=order.id,
                number=order.number,
                status=order.status,
                version=order.version,
            ),
            vehicle=VehicleRef(
                id=vehicle.id,
                make=vehicle.make,
                model=vehicle.model,
                plate_number=vehicle.plate_number,
            ),
            item_id=req.item_id,
            item_name=item.name if item else None,
            mechanic=UserRef(id=m.id, full_name=m.full_name),
            part=(
                PartFull(
                    id=part.id,
                    name=part.name,
                    sku=part.sku,
                    unit=part.unit,
                    sale_price=part.sale_price,
                    in_stock=stock.get((order.location_id, part.id)),
                )
                if part
                else None
            ),
            description=req.description,
            quantity=req.quantity,
            status=req.status,
            reject_reason=req.reject_reason,
            handled_by=UserRef(id=h.id, full_name=h.full_name) if h else None,
            handled_at=req.handled_at,
            created_at=req.created_at,
        )
    return [by_id[i] for i in ids if i in by_id]


async def list_requests(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID | None,
    status: str | None,
    order_id: uuid.UUID | None,
    mechanic_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> PartRequestFullPage:
    scope = work_orders._scope(location_id, allowed)
    conds: list[ColumnElement[bool]] = [WorkOrder.location_id.in_(scope)]
    if status is not None:
        conds.append(PartRequest.status == status)
    if order_id is not None:
        conds.append(PartRequest.work_order_id == order_id)
    if mechanic_id is not None:
        conds.append(PartRequest.mechanic_id == mechanic_id)
    total = await session.scalar(
        select(func.count())
        .select_from(PartRequest)
        .join(WorkOrder, WorkOrder.id == PartRequest.work_order_id)
        .where(*conds)
    )
    rank = case((PartRequest.status.in_(("new", "approved")), 0), else_=1)
    ids = list(
        await session.scalars(
            select(PartRequest.id)
            .join(WorkOrder, WorkOrder.id == PartRequest.work_order_id)
            .where(*conds)
            .order_by(rank, PartRequest.created_at, PartRequest.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return PartRequestFullPage(items=await _full_reads(session, ids), total=total or 0)


async def summary(
    session: AsyncSession, allowed: list[uuid.UUID], location_id: uuid.UUID | None
) -> PartRequestSummary:
    scope = work_orders._scope(location_id, allowed)
    rows = dict(
        (
            await session.execute(
                select(PartRequest.status, func.count())
                .join(WorkOrder, WorkOrder.id == PartRequest.work_order_id)
                .where(
                    WorkOrder.location_id.in_(scope),
                    PartRequest.status.in_(("new", "approved")),
                )
                .group_by(PartRequest.status)
            )
        ).all()
    )
    return PartRequestSummary(new=rows.get("new", 0), approved=rows.get("approved", 0))


async def _lock_request(
    session: AsyncSession, allowed: list[uuid.UUID], request_id: uuid.UUID
) -> tuple[PartRequest, WorkOrder]:
    """Заказ FOR UPDATE, затем заявка FOR UPDATE — тот же порядок, что в `add_part` модуля 5.

    Обратный порядок (заявка → заказ) взаимоблокировался бы с `POST …/parts` по той же заявке,
    а без блокировки заказа его статус мог смениться между проверкой и записью.
    """
    order_id = await session.scalar(
        select(PartRequest.work_order_id).where(PartRequest.id == request_id)
    )
    if order_id is None:
        raise AppError(404, "not_found")
    order = await session.get(WorkOrder, order_id, with_for_update=True, populate_existing=True)
    if order is None or order.location_id not in allowed:
        raise AppError(404, "not_found")
    req = await session.get(PartRequest, request_id, with_for_update=True, populate_existing=True)
    if req is None or req.work_order_id != order.id:
        raise AppError(404, "not_found")
    return req, order


async def _publish_handled(
    session: AsyncSession, actor: User, req: PartRequest, order: WorkOrder, status: str
) -> None:
    payload: dict[str, str | int | None] = {
        "request_id": str(req.id),
        "order_number": order.number,
        "description": req.description,
        "status": status,
    }
    if status == "rejected":
        payload["reject_reason"] = req.reject_reason
    await events.publish(
        session,
        "part_request.handled",
        payload,
        location_id=order.location_id,
        actor_id=actor.id,
        target_user_id=req.mechanic_id,
        dedup_key=f"part_request.handled:{req.id}:{status}",
    )


async def approve(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    request_id: uuid.UUID,
    data: PartApproveBody,
    client: ClientInfo,
) -> PartRequestFull:
    req, order = await _lock_request(session, allowed, request_id)
    if req.status != "new":
        raise AppError(409, "invalid_transition")
    if order.status in CLOSED:
        raise AppError(409, "invalid_state")
    changes: dict[str, object] = {"status": {"old": req.status, "new": "approved"}}
    if data.part_id is not None and data.part_id != req.part_id:
        part = await session.get(Part, data.part_id)
        if part is None or not part.is_active:
            raise _unprocessable(part_id="invalid")
        changes["part_id"] = {
            "old": str(req.part_id) if req.part_id else None,
            "new": str(part.id),
        }
        req.part_id = part.id
    req.status = "approved"
    req.handled_by = actor.id
    req.handled_at = timers.now()
    await session.flush()
    _audit_status(session, actor, req, order, changes, client)
    await _publish_handled(session, actor, req, order, "approved")
    await session.commit()
    return (await _full_reads(session, [req.id]))[0]


async def reject(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    request_id: uuid.UUID,
    data: PartRejectBody,
    client: ClientInfo,
) -> PartRequestFull:
    req, order = await _lock_request(session, allowed, request_id)
    if req.status not in ("new", "approved"):
        raise AppError(409, "invalid_transition")
    old = req.status
    req.status = "rejected"
    req.reject_reason = data.reason
    req.handled_by = actor.id
    req.handled_at = timers.now()
    await session.flush()
    _audit_status(
        session,
        actor,
        req,
        order,
        {
            "status": {"old": old, "new": "rejected"},
            "reject_reason": {"old": None, "new": data.reason},
        },
        client,
    )
    await _publish_handled(session, actor, req, order, "rejected")
    await session.commit()
    return (await _full_reads(session, [req.id]))[0]


async def issue(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    request_id: uuid.UUID,
    data: PartIssueBody,
    client: ClientInfo,
) -> PartIssueResult:
    """Выдача = добавление запчасти в заказ (`add_part` модуля 5 с `part_request_id`).

    Аудит и событие пишутся до `add_part`: он коммитит всё одной транзакцией, а при ошибке
    (`version_conflict`, `insufficient_stock`) сессия откатывается вместе с ними.
    """
    req, order = await _lock_request(session, allowed, request_id)
    if req.status not in ("new", "approved"):
        raise AppError(409, "invalid_transition")
    if order.status in CLOSED:
        raise AppError(409, "invalid_state")
    part_id = data.part_id or req.part_id
    if part_id is None:
        raise _unprocessable(part_id="required")
    quantity = data.quantity if data.quantity is not None else req.quantity
    old = req.status
    changes: dict[str, object] = {"status": {"old": old, "new": "issued"}}
    if part_id != req.part_id:
        changes["part_id"] = {
            "old": str(req.part_id) if req.part_id else None,
            "new": str(part_id),
        }
        req.part_id = part_id
        await session.flush()
    _audit_status(session, actor, req, order, changes, client)
    if old == "new":
        await _publish_handled(session, actor, req, order, "issued")
    body: dict[str, object] = {
        "version": data.version,
        "part_id": str(part_id),
        "quantity": f"{quantity:.3f}",
        "part_request_id": str(req.id),
    }
    if data.unit_price is not None:
        body["unit_price"] = f"{data.unit_price:.2f}"
    payload = PartCreate.model_validate(body)
    order_read = await work_orders.add_part(session, actor, allowed, order.id, payload, client)
    return PartIssueResult(request=(await _full_reads(session, [req.id]))[0], order=order_read)
