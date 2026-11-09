"""Адаптер модуля 9 к чтению заказа (модуль 5): тело заказа в ответе оплаты/возврата."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas.work_order import WorkOrderRead
from app.services import work_orders


async def order_read(
    session: AsyncSession, actor: User, allowed: list[uuid.UUID], order_id: uuid.UUID
) -> WorkOrderRead:
    return await work_orders.get_order(session, actor, allowed, order_id)
