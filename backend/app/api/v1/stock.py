import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AllowedLocations, Client, Director, SessionDep, Staff
from app.schemas.catalog import PartDepartment
from app.schemas.stock import (
    InventoryCommit,
    InventoryOut,
    MinQuantityUpdate,
    MovementPage,
    MovementsOut,
    MovementType,
    ReceiptCreate,
    ReverseCreate,
    SortDir,
    StockBalanceRead,
    StockMovementRead,
    StockPage,
    StockScope,
    StockSort,
    TransferCreate,
    TransferOut,
    WriteOffCreate,
)
from app.services import stock as svc

router = APIRouter(prefix="/stock", tags=["stock"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]


@router.get("", response_model=StockPage)
async def list_stock(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID,
    search: Annotated[str | None, Query(max_length=100)] = None,
    department: PartDepartment | None = None,
    scope: StockScope = "stocked",
    sort: StockSort = "name",
    order: SortDir = "asc",
    limit: Limit = 50,
    offset: Offset = 0,
) -> StockPage:
    return await svc.list_stock(
        session,
        allowed,
        location_id=location_id,
        search=search,
        department=department,
        scope=scope,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


# Статические пути объявлены раньше `/{part_id}`.
@router.get("/movements", response_model=MovementPage)
async def list_movements(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID,
    part_id: uuid.UUID | None = None,
    movement_type: MovementType | None = None,
    work_order_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> MovementPage:
    return await svc.list_movements(
        session,
        allowed,
        location_id=location_id,
        part_id=part_id,
        movement_type=movement_type,
        work_order_id=work_order_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.post("/receipts", response_model=MovementsOut, status_code=201)
async def create_receipt(
    data: ReceiptCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> MovementsOut:
    return await svc.create_receipt(session, actor, allowed, data, client)


@router.post("/write-offs", response_model=MovementsOut, status_code=201)
async def create_write_off(
    data: WriteOffCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> MovementsOut:
    return await svc.create_write_off(session, actor, allowed, data, client)


@router.post("/transfers", response_model=TransferOut, status_code=201)
async def create_transfer(
    data: TransferCreate, actor: Director, session: SessionDep, client: Client
) -> TransferOut:
    return await svc.create_transfer(session, actor, data, client)


@router.post("/inventory/commit", response_model=InventoryOut, status_code=201)
async def commit_inventory(
    data: InventoryCommit,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> InventoryOut:
    return await svc.commit_inventory(session, actor, allowed, data, client)


@router.post("/movements/{movement_id}/reverse", response_model=StockMovementRead, status_code=201)
async def reverse_movement(
    movement_id: uuid.UUID,
    data: ReverseCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> StockMovementRead:
    return await svc.reverse_movement(session, actor, allowed, movement_id, data, client)


@router.get("/{part_id}", response_model=StockBalanceRead)
async def get_stock(
    part_id: uuid.UUID,
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID,
) -> StockBalanceRead:
    return await svc.get_stock(session, allowed, location_id=location_id, part_id=part_id)


@router.patch("/{part_id}", response_model=StockBalanceRead)
async def set_min_quantity(
    part_id: uuid.UUID,
    data: MinQuantityUpdate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
    location_id: uuid.UUID,
) -> StockBalanceRead:
    return await svc.set_min_quantity(
        session,
        actor,
        allowed,
        location_id=location_id,
        part_id=part_id,
        data=data,
        client=client,
    )
