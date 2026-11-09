import uuid

from fastapi import APIRouter

from app.api.deps import Client, SessionDep, Staff
from app.schemas.client import VehicleCreate, VehicleDetail, VehicleRead, VehicleUpdate
from app.services import vehicles as svc

router = APIRouter(tags=["vehicles"])


@router.get("/clients/{client_id}/vehicles", response_model=list[VehicleRead])
async def list_client_vehicles(
    client_id: uuid.UUID, _: Staff, session: SessionDep, include_archived: bool = False
) -> list[VehicleRead]:
    return await svc.list_vehicles(session, client_id, include_archived)


@router.post("/clients/{client_id}/vehicles", response_model=VehicleRead, status_code=201)
async def create_vehicle(
    client_id: uuid.UUID, data: VehicleCreate, actor: Staff, session: SessionDep, client: Client
) -> VehicleRead:
    return await svc.create_vehicle(session, actor, client_id, data, client)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleDetail)
async def get_vehicle(vehicle_id: uuid.UUID, _: Staff, session: SessionDep) -> VehicleDetail:
    return await svc.get_vehicle_detail(session, vehicle_id)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleRead)
async def update_vehicle(
    vehicle_id: uuid.UUID, data: VehicleUpdate, actor: Staff, session: SessionDep, client: Client
) -> VehicleRead:
    return await svc.update_vehicle(session, actor, vehicle_id, data, client)


@router.post("/vehicles/{vehicle_id}/archive", response_model=VehicleRead)
async def archive_vehicle(
    vehicle_id: uuid.UUID, actor: Staff, session: SessionDep, client: Client
) -> VehicleRead:
    return await svc.set_archived(session, actor, vehicle_id, True, client)


@router.post("/vehicles/{vehicle_id}/restore", response_model=VehicleRead)
async def restore_vehicle(
    vehicle_id: uuid.UUID, actor: Staff, session: SessionDep, client: Client
) -> VehicleRead:
    return await svc.set_archived(session, actor, vehicle_id, False, client)
