import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import AllowedLocations, Client, SessionDep, Staff
from app.schemas.work_order import (
    CommentCreate,
    EmptyBody,
    ItemCreate,
    ItemUpdate,
    OrderBoard,
    OrderSummary,
    PartCreate,
    PartUpdate,
    StatusChangeBody,
    StatusHistoryEntry,
    UserRef,
    VersionBody,
    WorkOrderCommentRead,
    WorkOrderCreate,
    WorkOrderDepartment,
    WorkOrderPage,
    WorkOrderRead,
    WorkOrderUpdate,
)
from app.services import work_order_print as printing
from app.services import work_orders as svc

router = APIRouter(prefix="/work-orders", tags=["work-orders"])

PaymentStatusQ = Literal["unpaid", "partial", "paid", "refunded"]
VersionQ = Annotated[int, Query(ge=1, le=2_147_483_647)]


# ---------- список, доска, счётчики ----------


@router.get("", response_model=WorkOrderPage)
async def list_orders(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    status: Annotated[str | None, Query(max_length=200)] = None,
    department: WorkOrderDepartment | None = None,
    manager_id: uuid.UUID | None = None,
    mechanic_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    payment_status: PaymentStatusQ | None = None,
    overdue: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    sort: Literal["created_at", "planned_ready_at", "number", "total", "status"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> WorkOrderPage:
    return await svc.list_orders(
        session,
        allowed,
        location_id=location_id,
        status=status,
        department=department,
        manager_id=manager_id,
        mechanic_id=mechanic_id,
        client_id=client_id,
        vehicle_id=vehicle_id,
        payment_status=payment_status,
        overdue=overdue,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/board", response_model=OrderBoard)
async def board(
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    department: WorkOrderDepartment | None = None,
    manager_id: uuid.UUID | None = None,
    mechanic_id: uuid.UUID | None = None,
    overdue: bool | None = None,
) -> OrderBoard:
    return await svc.board(
        session,
        actor,
        allowed,
        location_id=location_id,
        department=department,
        manager_id=manager_id,
        mechanic_id=mechanic_id,
        overdue=overdue,
    )


@router.get("/summary", response_model=OrderSummary)
async def summary(
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
) -> OrderSummary:
    return await svc.summary(session, actor, allowed, location_id)


@router.get("/mechanics", response_model=list[UserRef])
async def mechanics(
    _: Staff, session: SessionDep, allowed: AllowedLocations, location_id: uuid.UUID
) -> list[UserRef]:
    return await svc.list_mechanics(session, allowed, location_id)


# ---------- заказ ----------


@router.post("", response_model=WorkOrderRead, status_code=201)
async def create_order(
    data: WorkOrderCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.create_order(session, actor, allowed, data, client)


@router.get("/{order_id}", response_model=WorkOrderRead)
async def get_order(
    order_id: uuid.UUID, actor: Staff, session: SessionDep, allowed: AllowedLocations
) -> WorkOrderRead:
    return await svc.get_order(session, actor, allowed, order_id)


@router.patch("/{order_id}", response_model=WorkOrderRead)
async def update_order(
    order_id: uuid.UUID,
    data: WorkOrderUpdate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.update_order(session, actor, allowed, order_id, data, client)


@router.post("/{order_id}/status", response_model=WorkOrderRead)
async def change_status(
    order_id: uuid.UUID,
    data: StatusChangeBody,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.change_status(session, actor, allowed, order_id, data, client)


@router.get("/{order_id}/history", response_model=list[StatusHistoryEntry])
async def status_history(
    order_id: uuid.UUID, _: Staff, session: SessionDep, allowed: AllowedLocations
) -> list[StatusHistoryEntry]:
    return await svc.status_history(session, allowed, order_id)


@router.post("/{order_id}/duplicate", response_model=WorkOrderRead, status_code=201)
async def duplicate_order(
    order_id: uuid.UUID,
    _data: EmptyBody,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.duplicate_order(session, actor, allowed, order_id, client)


# ---------- работы ----------


@router.post("/{order_id}/items", response_model=WorkOrderRead, status_code=201)
async def add_item(
    order_id: uuid.UUID,
    data: ItemCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.add_item(session, actor, allowed, order_id, data, client)


@router.patch("/{order_id}/items/{item_id}", response_model=WorkOrderRead)
async def update_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ItemUpdate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.update_item(session, actor, allowed, order_id, item_id, data, client)


@router.delete("/{order_id}/items/{item_id}", response_model=WorkOrderRead)
async def delete_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    version: VersionQ,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.delete_item(session, actor, allowed, order_id, item_id, version, client)


@router.post("/{order_id}/items/{item_id}/cancel", response_model=WorkOrderRead)
async def cancel_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: VersionBody,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.cancel_item(session, actor, allowed, order_id, item_id, data.version, client)


@router.post("/{order_id}/items/{item_id}/complete", response_model=WorkOrderRead)
async def complete_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: VersionBody,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.complete_item(
        session, actor, allowed, order_id, item_id, data.version, client
    )


# ---------- запчасти ----------


@router.post("/{order_id}/parts", response_model=WorkOrderRead, status_code=201)
async def add_part(
    order_id: uuid.UUID,
    data: PartCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.add_part(session, actor, allowed, order_id, data, client)


@router.patch("/{order_id}/parts/{row_id}", response_model=WorkOrderRead)
async def update_part(
    order_id: uuid.UUID,
    row_id: uuid.UUID,
    data: PartUpdate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.update_part(session, actor, allowed, order_id, row_id, data, client)


@router.delete("/{order_id}/parts/{row_id}", response_model=WorkOrderRead)
async def delete_part(
    order_id: uuid.UUID,
    row_id: uuid.UUID,
    version: VersionQ,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderRead:
    return await svc.delete_part(session, actor, allowed, order_id, row_id, version, client)


# ---------- комментарии ----------


@router.get("/{order_id}/comments", response_model=list[WorkOrderCommentRead])
async def list_comments(
    order_id: uuid.UUID,
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    is_internal: bool | None = None,
) -> list[WorkOrderCommentRead]:
    return await svc.list_comments(session, allowed, order_id, is_internal)


@router.post("/{order_id}/comments", response_model=WorkOrderCommentRead, status_code=201)
async def add_comment(
    order_id: uuid.UUID,
    data: CommentCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> WorkOrderCommentRead:
    return await svc.add_comment(session, actor, allowed, order_id, data, client)


# ---------- печатные формы ----------


async def _pdf(
    kind: Literal["work-order", "act"],
    order_id: uuid.UUID,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
) -> Response:
    content, filename = await printing.render(session, actor, allowed, order_id, kind)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/{order_id}/print/work-order", response_class=Response)
async def print_work_order(
    order_id: uuid.UUID, actor: Staff, session: SessionDep, allowed: AllowedLocations
) -> Response:
    return await _pdf("work-order", order_id, actor, session, allowed)


@router.get("/{order_id}/print/act", response_class=Response)
async def print_act(
    order_id: uuid.UUID, actor: Staff, session: SessionDep, allowed: AllowedLocations
) -> Response:
    return await _pdf("act", order_id, actor, session, allowed)
