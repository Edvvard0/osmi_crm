import uuid

from fastapi import APIRouter

from app.api.deps import AllowedLocations, Client, CurrentUser, Director, SessionDep
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate
from app.services import locations as svc

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=list[LocationRead])
async def list_locations(
    user: CurrentUser, session: SessionDep, allowed: AllowedLocations
) -> list[LocationRead]:
    return await svc.list_locations(session, allowed, user)


@router.post("", response_model=LocationRead, status_code=201)
async def create_location(
    data: LocationCreate, actor: Director, session: SessionDep, client: Client
) -> LocationRead:
    return await svc.create_location(session, actor, data, client)


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    location_id: uuid.UUID, user: CurrentUser, session: SessionDep, allowed: AllowedLocations
) -> LocationRead:
    return svc.to_read(await svc.get_location(session, location_id, allowed), user)


@router.patch("/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: uuid.UUID,
    data: LocationUpdate,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> LocationRead:
    return await svc.update_location(session, actor, location_id, data, client)
