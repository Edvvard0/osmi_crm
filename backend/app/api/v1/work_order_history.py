"""История заказ-нарядов клиента и автомобиля (MG-09, MG-10)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AllowedLocations, SessionDep, Staff
from app.schemas.work_order import WorkOrderPage
from app.services import work_orders as svc

router = APIRouter(tags=["work-orders"])


@router.get("/clients/{client_id}/work-orders", response_model=WorkOrderPage)
async def client_orders(
    client_id: uuid.UUID,
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    status: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> WorkOrderPage:
    return await svc.history_of_subject(
        session, allowed, client_id=client_id, status=status, limit=limit, offset=offset
    )


@router.get("/vehicles/{vehicle_id}/work-orders", response_model=WorkOrderPage)
async def vehicle_orders(
    vehicle_id: uuid.UUID,
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    status: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> WorkOrderPage:
    return await svc.history_of_subject(
        session, allowed, vehicle_id=vehicle_id, status=status, limit=limit, offset=offset
    )
