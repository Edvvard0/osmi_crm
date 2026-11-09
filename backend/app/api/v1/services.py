import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import AllowedLocations, Client, Director, SessionDep, Staff
from app.schemas.catalog import (
    Department,
    PriceSet,
    ServiceCreate,
    ServicePage,
    ServicePriceRead,
    ServiceRead,
    ServiceUpdate,
)
from app.services import catalog as svc

router = APIRouter(tags=["catalog"])


@router.get("/services", response_model=ServicePage)
async def list_services(
    user: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    search: Annotated[str | None, Query(max_length=100)] = None,
    category_id: uuid.UUID | None = None,
    department: Department | None = None,
    is_active: bool | None = None,
    location_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ServicePage:
    location = svc.resolve_price_location(user, location_id, allowed)
    return await svc.list_services(
        session,
        search=search,
        category_id=category_id,
        department=department,
        is_active=is_active,
        location_id=location,
        limit=limit,
        offset=offset,
    )


@router.post("/services", response_model=ServiceRead, status_code=201)
async def create_service(
    data: ServiceCreate, actor: Director, session: SessionDep, client: Client
) -> ServiceRead:
    return await svc.create_service(session, actor, data, client)


@router.get("/services/{service_id}", response_model=ServiceRead)
async def get_service(
    service_id: uuid.UUID,
    user: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
) -> ServiceRead:
    location = svc.resolve_price_location(user, location_id, allowed)
    return await svc.get_service_read(session, service_id, location)


@router.patch("/services/{service_id}", response_model=ServiceRead)
async def update_service(
    service_id: uuid.UUID,
    data: ServiceUpdate,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> ServiceRead:
    return await svc.update_service(session, actor, service_id, data, client)


# Цены по точкам: только руководитель.


@router.get("/service-prices", response_model=list[ServicePriceRead])
async def list_location_prices(
    _: Director, session: SessionDep, location_id: uuid.UUID
) -> list[ServicePriceRead]:
    return await svc.list_location_prices(session, location_id)


@router.get("/services/{service_id}/prices", response_model=list[ServicePriceRead])
async def list_service_prices(
    service_id: uuid.UUID, _: Director, session: SessionDep
) -> list[ServicePriceRead]:
    return await svc.list_service_prices(session, service_id)


@router.put("/services/{service_id}/prices/{location_id}", response_model=ServicePriceRead)
async def set_price(
    service_id: uuid.UUID,
    location_id: uuid.UUID,
    data: PriceSet,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> ServicePriceRead:
    return await svc.set_price(session, actor, service_id, location_id, data.price, client)


@router.delete("/services/{service_id}/prices/{location_id}", status_code=204)
async def delete_price(
    service_id: uuid.UUID,
    location_id: uuid.UUID,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> Response:
    await svc.delete_price(session, actor, service_id, location_id, client)
    return Response(status_code=204)
