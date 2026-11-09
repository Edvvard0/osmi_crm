import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import Client, SessionDep, Staff
from app.schemas.client import ClientCreate, ClientDetail, ClientPage, ClientRead, ClientUpdate
from app.services import clients as svc

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=ClientPage)
async def list_clients(
    _: Staff,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    client_type: Literal["person", "company"] | None = None,
    source: Literal["walk_in", "referral", "online", "ads", "repeat", "other"] | None = None,
    archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ClientPage:
    return await svc.list_clients(
        session,
        search=search,
        client_type=client_type,
        source=source,
        archived=archived,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ClientRead, status_code=201)
async def create_client(
    data: ClientCreate, actor: Staff, session: SessionDep, client: Client
) -> ClientRead:
    return await svc.create_client(session, actor, data, client)


@router.get("/{client_id}", response_model=ClientDetail)
async def get_client(client_id: uuid.UUID, _: Staff, session: SessionDep) -> ClientDetail:
    return await svc.get_client_detail(session, client_id)


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: uuid.UUID, data: ClientUpdate, actor: Staff, session: SessionDep, client: Client
) -> ClientRead:
    return await svc.update_client(session, actor, client_id, data, client)


@router.post("/{client_id}/archive", response_model=ClientRead)
async def archive_client(
    client_id: uuid.UUID, actor: Staff, session: SessionDep, client: Client
) -> ClientRead:
    return await svc.set_archived(session, actor, client_id, True, client)


@router.post("/{client_id}/restore", response_model=ClientRead)
async def restore_client(
    client_id: uuid.UUID, actor: Staff, session: SessionDep, client: Client
) -> ClientRead:
    return await svc.set_archived(session, actor, client_id, False, client)
