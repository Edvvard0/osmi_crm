import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AllowedLocations, CurrentUser, SessionDep
from app.schemas.activity import ActivityDetails, ActivityHeatmap
from app.services import activity

router = APIRouter(tags=["activity"])


@router.get(
    "/users/{user_id}/activity-heatmap",
    response_model=ActivityHeatmap,
    response_model_by_alias=True,
)
async def get_heatmap(
    user_id: uuid.UUID,
    actor: CurrentUser,
    session: SessionDep,
    allowed: AllowedLocations,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> ActivityHeatmap:
    return await activity.heatmap(session, actor, allowed, user_id, date_from, date_to)


@router.get("/users/{user_id}/activity-details", response_model=ActivityDetails)
async def get_details(
    user_id: uuid.UUID,
    actor: CurrentUser,
    session: SessionDep,
    allowed: AllowedLocations,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ActivityDetails:
    return await activity.details(session, actor, allowed, user_id, date_from, date_to)
