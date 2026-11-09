import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AllowedLocations, Client, SessionDep, require_role
from app.models import User
from app.models.enums import Role
from app.schemas.mechanic import (
    CommentCreate,
    FinishBody,
    FinishResult,
    MechanicComment,
    MechanicPart,
    MechanicRecommendationCreate,
    MechanicTaskDetail,
    PartRequestCreate,
    PartRequestPage,
    PartRequestRead,
    PartRequestStatus,
    PauseResult,
    StartBody,
    StartResult,
    TaskList,
    TaskScope,
    VehicleRecommendation,
)
from app.services import mechanic as svc
from app.services import part_requests, recommendations

router = APIRouter(prefix="/mechanic", tags=["mechanic"])

Mechanic = Annotated[User, Depends(require_role(Role.mechanic))]


@router.get("/tasks", response_model=TaskList)
async def list_tasks(
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    scope: TaskScope = "open",
) -> TaskList:
    return await svc.list_tasks(session, user, allowed, scope)


@router.get("/tasks/{item_id}", response_model=MechanicTaskDetail)
async def get_task(
    item_id: uuid.UUID, user: Mechanic, allowed: AllowedLocations, session: SessionDep
) -> MechanicTaskDetail:
    return await svc.get_task(session, user, allowed, item_id)


@router.post("/tasks/{item_id}/start", response_model=StartResult)
async def start_task(
    item_id: uuid.UUID,
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
    data: StartBody | None = None,
) -> StartResult:
    return await svc.start_task(session, user, allowed, item_id, data or StartBody(), client)


@router.post("/tasks/{item_id}/pause", response_model=PauseResult)
async def pause_task(
    item_id: uuid.UUID,
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> PauseResult:
    return await svc.pause_task(session, user, allowed, item_id, client)


@router.post("/tasks/{item_id}/finish", response_model=FinishResult)
async def finish_task(
    item_id: uuid.UUID,
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
    data: FinishBody | None = None,
) -> FinishResult:
    return await svc.finish_task(session, user, allowed, item_id, data or FinishBody(), client)


@router.post("/tasks/{item_id}/comments", response_model=MechanicComment, status_code=201)
async def add_comment(
    item_id: uuid.UUID,
    data: CommentCreate,
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> MechanicComment:
    return await svc.add_comment(session, user, allowed, item_id, data, client)


@router.post("/part-requests", response_model=PartRequestRead, status_code=201)
async def create_part_request(
    data: PartRequestCreate,
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> PartRequestRead:
    return await part_requests.create_for_mechanic(session, user, allowed, data, client)


@router.get("/part-requests", response_model=PartRequestPage)
async def list_part_requests(
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    status: PartRequestStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PartRequestPage:
    return await part_requests.list_for_mechanic(session, user, allowed, status, limit, offset)


@router.post("/recommendations", response_model=VehicleRecommendation, status_code=201)
async def create_recommendation(
    data: MechanicRecommendationCreate,
    user: Mechanic,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> VehicleRecommendation:
    return await recommendations.create_for_mechanic(session, user, allowed, data, client)


@router.get("/parts", response_model=list[MechanicPart])
async def search_parts(
    _: Mechanic,
    session: SessionDep,
    search: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[MechanicPart]:
    return await svc.search_parts(session, search, limit)
