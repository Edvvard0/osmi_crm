import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import Client, Director, SessionDep, Staff
from app.schemas.catalog import PartCreate, PartDepartment, PartPage, PartRead, PartUpdate
from app.services import catalog as svc

router = APIRouter(prefix="/parts", tags=["catalog"])


@router.get("", response_model=PartPage)
async def list_parts(
    _: Staff,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    department: PartDepartment | None = None,
    is_active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PartPage:
    return await svc.list_parts(
        session,
        search=search,
        department=department,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=PartRead, status_code=201)
async def create_part(
    data: PartCreate, actor: Director, session: SessionDep, client: Client
) -> PartRead:
    return await svc.create_part(session, actor, data, client)


@router.patch("/{part_id}", response_model=PartRead)
async def update_part(
    part_id: uuid.UUID, data: PartUpdate, actor: Director, session: SessionDep, client: Client
) -> PartRead:
    return await svc.update_part(session, actor, part_id, data, client)
