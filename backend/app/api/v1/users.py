import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import Client, Director, SessionDep
from app.models import Role
from app.schemas.user import ResetPassword, UserCreate, UserPage, UserRead, UserUpdate
from app.services import users as svc

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserPage)
async def list_users(
    _: Director,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: Role | None = None,
    location_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> UserPage:
    return await svc.list_users(
        session,
        search=search,
        role=role,
        location_id=location_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UserRead, status_code=201)
async def create_user(
    data: UserCreate, actor: Director, session: SessionDep, client: Client
) -> UserRead:
    return await svc.create_user(session, actor, data, client)


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, _: Director, session: SessionDep) -> UserRead:
    return await svc.read_user(session, await svc.get_user(session, user_id))


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, actor: Director, session: SessionDep, client: Client
) -> UserRead:
    return await svc.update_user(session, actor, user_id, data, client)


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password(
    user_id: uuid.UUID, data: ResetPassword, actor: Director, session: SessionDep, client: Client
) -> Response:
    await svc.reset_password(session, actor, user_id, data.new_password, client)
    return Response(status_code=204)
