import uuid

from fastapi import APIRouter

from app.api.deps import AllowedLocations, Client, CurrentUser, Director, SessionDep
from app.schemas.catalog import PostCreate, PostRead, PostUpdate
from app.services import catalog as svc

router = APIRouter(tags=["catalog"])


@router.get("/locations/{location_id}/posts", response_model=list[PostRead])
async def list_posts(
    location_id: uuid.UUID,
    _: CurrentUser,
    session: SessionDep,
    allowed: AllowedLocations,
    is_active: bool | None = None,
) -> list[PostRead]:
    return await svc.list_posts(session, location_id, allowed, is_active=is_active)


@router.post("/locations/{location_id}/posts", response_model=PostRead, status_code=201)
async def create_post(
    location_id: uuid.UUID,
    data: PostCreate,
    actor: Director,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> PostRead:
    return await svc.create_post(session, actor, location_id, allowed, data, client)


@router.patch("/posts/{post_id}", response_model=PostRead)
async def update_post(
    post_id: uuid.UUID, data: PostUpdate, actor: Director, session: SessionDep, client: Client
) -> PostRead:
    return await svc.update_post(session, actor, post_id, data, client)
