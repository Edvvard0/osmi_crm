"""Рекомендации по автомобилю (модуль 6): от механика и от менеджера."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import AppError
from app.models import User, Vehicle
from app.models.mechanic import VehicleRecommendation as Recommendation
from app.models.work_order import WorkOrder
from app.schemas.mechanic import (
    MechanicRecommendationCreate,
    RecommendationCreate,
    RecommendationUpdate,
    UserRef,
    VehicleRecommendation,
)
from app.services.audit import ClientInfo, write_audit
from app.services.mechanic import load_item


def _read(
    rec: Recommendation, order_number: str | None, author: User
) -> VehicleRecommendation:
    return VehicleRecommendation(
        id=rec.id,
        vehicle_id=rec.vehicle_id,
        work_order_id=rec.work_order_id,
        work_order_number=order_number,
        text=rec.text,
        priority=rec.priority,
        status=rec.status,
        created_by=UserRef(id=author.id, full_name=author.full_name),
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


def _created(rec: Recommendation) -> dict[str, dict[str, str | None]]:
    """Формат журнала, как у остальных сущностей: {поле: {"old": None, "new": значение}}."""
    values = {
        "vehicle_id": str(rec.vehicle_id),
        "work_order_id": str(rec.work_order_id) if rec.work_order_id else None,
        "priority": rec.priority,
        "text": rec.text,
    }
    return {k: {"old": None, "new": v} for k, v in values.items()}


async def _order_number(session: AsyncSession, order_id: uuid.UUID | None) -> str | None:
    if order_id is None:
        return None
    return await session.scalar(select(WorkOrder.number).where(WorkOrder.id == order_id))


async def create_for_mechanic(
    session: AsyncSession,
    user: User,
    allowed: list[uuid.UUID],
    data: MechanicRecommendationCreate,
    client: ClientInfo,
) -> VehicleRecommendation:
    _, order = await load_item(session, user, allowed, data.item_id)
    rec = Recommendation(
        vehicle_id=order.vehicle_id,
        work_order_id=order.id,
        text=data.text,
        priority=data.priority,
        status="open",
        created_by=user.id,
    )
    session.add(rec)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="vehicle_recommendation",
        entity_id=rec.id,
        location_id=order.location_id,
        user_id=user.id,
        changes=_created(rec),
        client=client,
    )
    await session.commit()
    await session.refresh(rec)
    return _read(rec, order.number, user)


# ---------------- менеджер / директор ----------------


async def _vehicle(session: AsyncSession, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise AppError(404, "not_found")
    return vehicle


async def _check_order(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    vehicle_id: uuid.UUID,
    order_id: uuid.UUID,
) -> WorkOrder:
    order = await session.get(WorkOrder, order_id)
    if order is None or order.location_id not in allowed or order.vehicle_id != vehicle_id:
        raise AppError(422, "validation_error", {"work_order_id": "invalid"})
    return order


async def list_for_vehicle(
    session: AsyncSession, vehicle_id: uuid.UUID, status: str | None
) -> list[VehicleRecommendation]:
    await _vehicle(session, vehicle_id)
    author = aliased(User)
    stmt = (
        select(Recommendation, WorkOrder.number, author)
        .join(author, author.id == Recommendation.created_by)
        .outerjoin(WorkOrder, WorkOrder.id == Recommendation.work_order_id)
        .where(Recommendation.vehicle_id == vehicle_id)
        .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
    )
    if status is not None:
        stmt = stmt.where(Recommendation.status == status)
    rows = (await session.execute(stmt)).all()
    return [_read(rec, number, a) for rec, number, a in rows]


async def create_for_vehicle(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    vehicle_id: uuid.UUID,
    data: RecommendationCreate,
    client: ClientInfo,
) -> VehicleRecommendation:
    await _vehicle(session, vehicle_id)
    order: WorkOrder | None = None
    if data.work_order_id is not None:
        order = await _check_order(session, allowed, vehicle_id, data.work_order_id)
    rec = Recommendation(
        vehicle_id=vehicle_id,
        work_order_id=order.id if order else None,
        text=data.text,
        priority=data.priority,
        status="open",
        created_by=actor.id,
    )
    session.add(rec)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="vehicle_recommendation",
        entity_id=rec.id,
        location_id=order.location_id if order else None,
        user_id=actor.id,
        changes=_created(rec),
        client=client,
    )
    await session.commit()
    await session.refresh(rec)
    return _read(rec, order.number if order else None, actor)


async def update(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    recommendation_id: uuid.UUID,
    data: RecommendationUpdate,
    client: ClientInfo,
) -> VehicleRecommendation:
    rec = await session.get(
        Recommendation, recommendation_id, with_for_update=True, populate_existing=True
    )
    if rec is None:
        raise AppError(404, "not_found")
    values = data.model_dump(exclude_unset=True)
    changes: dict[str, object] = {}
    location_id: uuid.UUID | None = None
    if "work_order_id" in values:
        wid = values["work_order_id"]
        if wid is not None:
            order = await _check_order(session, allowed, rec.vehicle_id, wid)
            location_id = order.location_id
        if wid != rec.work_order_id:
            changes["work_order_id"] = {
                "old": str(rec.work_order_id) if rec.work_order_id else None,
                "new": str(wid) if wid else None,
            }
            rec.work_order_id = wid
    for field in ("status", "priority", "text"):
        if field in values and values[field] is not None and values[field] != getattr(rec, field):
            changes[field] = {"old": getattr(rec, field), "new": values[field]}
            setattr(rec, field, values[field])
    if changes:
        await session.flush()
        if location_id is None and rec.work_order_id is not None:
            linked = await session.get(WorkOrder, rec.work_order_id)
            location_id = linked.location_id if linked else None
        write_audit(
            session,
            action="update",
            entity_type="vehicle_recommendation",
            entity_id=rec.id,
            location_id=location_id,
            user_id=actor.id,
            changes=changes,
            client=client,
        )
        await session.commit()
        await session.refresh(rec)
    author = await session.get(User, rec.created_by)
    assert author is not None
    return _read(rec, await _order_number(session, rec.work_order_id), author)
