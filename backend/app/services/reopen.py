"""Возврат выполненной работы в исполнение (модуль 6, менеджер / директор)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import User
from app.schemas.mechanic import ReopenBody
from app.schemas.work_order import WorkOrderRead
from app.services import work_orders
from app.services.audit import ClientInfo, write_audit

COMMENT = "Работа возвращена в исполнение"


async def reopen(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ReopenBody,
    client: ClientInfo,
) -> WorkOrderRead:
    order = await work_orders._get_order(session, allowed, order_id, for_update=True)
    work_orders._check_version(order, data.version)
    if order.status in ("closed", "cancelled"):
        raise AppError(409, "invalid_state")
    items = await work_orders._items_of(session, order.id)
    item = next((i for i in items if i.id == item_id), None)
    if item is None:
        raise AppError(404, "not_found")
    if item.status != "done":
        raise AppError(409, "invalid_state")
    parts = await work_orders._parts_of(session, order.id)
    old_max = work_orders.max_discount(order, items)

    item.status = "paused"
    item.finished_at = None
    old_order_status = order.status
    if old_order_status in ("quality_check", "ready"):
        order.status = "in_progress"
        if old_order_status == "ready":
            order.ready_at = None
        await work_orders._history(
            session, order, old_order_status, "in_progress", actor.id, COMMENT
        )
    await session.flush()
    await work_orders._save(session, actor, order, items, parts, old_max_discount=old_max)
    write_audit(
        session,
        action="status_change",
        entity_type="work_order_item",
        entity_id=item.id,
        location_id=order.location_id,
        user_id=actor.id,
        changes={
            "status": {"old": "done", "new": "paused"},
            "work_order_id": {"old": None, "new": str(order.id)},
        },
        client=client,
    )
    if old_order_status != order.status:
        write_audit(
            session,
            action="status_change",
            entity_type="work_order",
            entity_id=order.id,
            location_id=order.location_id,
            user_id=actor.id,
            changes={"status": {"old": old_order_status, "new": order.status}},
            client=client,
        )
    await work_orders._publish_item_updated(session, actor, order, item, "reopened")
    await session.commit()
    return await work_orders._respond(session, actor, order)
