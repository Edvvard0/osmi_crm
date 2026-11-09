import uuid
from datetime import date

from fastapi import APIRouter

from app.api.deps import AllowedLocations, Client, SessionDep, Staff
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentStatus,
    AppointmentUpdate,
    StatusChange,
)
from app.schemas.catalog import Department
from app.services import appointments as svc

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("", response_model=list[AppointmentRead])
async def list_appointments(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID,
    date_from: date,
    date_to: date,
    post_id: uuid.UUID | None = None,
    department: Department | None = None,
    status: AppointmentStatus | None = None,
    client_id: uuid.UUID | None = None,
) -> list[AppointmentRead]:
    return await svc.list_appointments(
        session,
        allowed,
        location_id=location_id,
        date_from=date_from,
        date_to=date_to,
        post_id=post_id,
        department=department,
        status=status,
        client_id=client_id,
    )


@router.post("", response_model=AppointmentRead, status_code=201)
async def create_appointment(
    data: AppointmentCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> AppointmentRead:
    return await svc.create_appointment(session, actor, allowed, data, client)


@router.get("/{appointment_id}", response_model=AppointmentRead)
async def get_appointment(
    appointment_id: uuid.UUID, _: Staff, session: SessionDep, allowed: AllowedLocations
) -> AppointmentRead:
    return await svc.get_appointment(session, allowed, appointment_id)


@router.patch("/{appointment_id}", response_model=AppointmentRead)
async def update_appointment(
    appointment_id: uuid.UUID,
    data: AppointmentUpdate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> AppointmentRead:
    return await svc.update_appointment(session, actor, allowed, appointment_id, data, client)


@router.post("/{appointment_id}/status", response_model=AppointmentRead)
async def change_status(
    appointment_id: uuid.UUID,
    data: StatusChange,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> AppointmentRead:
    return await svc.change_status(session, actor, allowed, appointment_id, data.status, client)
