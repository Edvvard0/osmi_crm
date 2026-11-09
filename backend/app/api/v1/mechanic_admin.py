"""Менеджерская часть модуля 6: заявки на запчасти, возврат работы, рекомендации по авто."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AllowedLocations, Client, SessionDep, Staff
from app.schemas.mechanic import (
    PartApproveBody,
    PartIssueBody,
    PartIssueResult,
    PartRejectBody,
    PartRequestFull,
    PartRequestFullPage,
    PartRequestStatus,
    PartRequestSummary,
    RecommendationCreate,
    RecommendationStatus,
    RecommendationUpdate,
    ReopenBody,
    VehicleRecommendation,
)
from app.schemas.work_order import WorkOrderRead
from app.services import part_requests, recommendations, reopen

router = APIRouter(tags=["mechanic"])


@router.get("/part-requests", response_model=PartRequestFullPage)
async def list_part_requests(
    _: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    location_id: uuid.UUID | None = None,
    status: PartRequestStatus | None = None,
    order_id: uuid.UUID | None = None,
    mechanic_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PartRequestFullPage:
    return await part_requests.list_requests(
        session,
        allowed,
        location_id=location_id,
        status=status,
        order_id=order_id,
        mechanic_id=mechanic_id,
        limit=limit,
        offset=offset,
    )


# Статический путь объявлен раньше `/{request_id}/...`.
@router.get("/part-requests/summary", response_model=PartRequestSummary)
async def part_requests_summary(
    _: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    location_id: uuid.UUID | None = None,
) -> PartRequestSummary:
    return await part_requests.summary(session, allowed, location_id)


@router.post("/part-requests/{request_id}/approve", response_model=PartRequestFull)
async def approve_part_request(
    request_id: uuid.UUID,
    actor: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
    data: PartApproveBody | None = None,
) -> PartRequestFull:
    return await part_requests.approve(
        session, actor, allowed, request_id, data or PartApproveBody(), client
    )


@router.post("/part-requests/{request_id}/reject", response_model=PartRequestFull)
async def reject_part_request(
    request_id: uuid.UUID,
    data: PartRejectBody,
    actor: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> PartRequestFull:
    return await part_requests.reject(session, actor, allowed, request_id, data, client)


@router.post("/part-requests/{request_id}/issue", response_model=PartIssueResult)
async def issue_part_request(
    request_id: uuid.UUID,
    data: PartIssueBody,
    actor: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> PartIssueResult:
    return await part_requests.issue(session, actor, allowed, request_id, data, client)


@router.post("/work-orders/{order_id}/items/{item_id}/reopen", response_model=WorkOrderRead)
async def reopen_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ReopenBody,
    actor: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> WorkOrderRead:
    return await reopen.reopen(session, actor, allowed, order_id, item_id, data, client)


@router.get("/vehicles/{vehicle_id}/recommendations", response_model=list[VehicleRecommendation])
async def list_recommendations(
    vehicle_id: uuid.UUID,
    _: Staff,
    session: SessionDep,
    status: RecommendationStatus | None = None,
) -> list[VehicleRecommendation]:
    return await recommendations.list_for_vehicle(session, vehicle_id, status)


@router.post(
    "/vehicles/{vehicle_id}/recommendations",
    response_model=VehicleRecommendation,
    status_code=201,
)
async def create_recommendation(
    vehicle_id: uuid.UUID,
    data: RecommendationCreate,
    actor: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> VehicleRecommendation:
    return await recommendations.create_for_vehicle(
        session, actor, allowed, vehicle_id, data, client
    )


@router.patch("/recommendations/{recommendation_id}", response_model=VehicleRecommendation)
async def update_recommendation(
    recommendation_id: uuid.UUID,
    data: RecommendationUpdate,
    actor: Staff,
    allowed: AllowedLocations,
    session: SessionDep,
    client: Client,
) -> VehicleRecommendation:
    return await recommendations.update(session, actor, allowed, recommendation_id, data, client)
