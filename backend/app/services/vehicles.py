import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Client, User, Vehicle
from app.schemas.client import (
    VehicleCreate,
    VehicleDetail,
    VehicleOwner,
    VehicleRead,
    VehicleUpdate,
)
from app.services.audit import ClientInfo, diff, write_audit
from app.services.sessions import utcnow

_FIELDS = ("make", "model", "year", "vin", "plate_number", "color", "mileage", "notes")


def to_read(v: Vehicle) -> VehicleRead:
    return VehicleRead(
        id=v.id,
        client_id=v.client_id,
        make=v.make,
        model=v.model,
        year=v.year,
        vin=v.vin,
        plate_number=v.plate_number,
        color=v.color,
        mileage=v.mileage,
        notes=v.notes,
        created_at=v.created_at,
        archived_at=v.archived_at,
    )


def _snapshot(v: Vehicle) -> dict[str, Any]:
    return {f: getattr(v, f) for f in _FIELDS}


async def get_vehicle(
    session: AsyncSession, vehicle_id: uuid.UUID, *, for_update: bool = False
) -> Vehicle:
    vehicle = await session.get(Vehicle, vehicle_id, with_for_update=for_update)
    if vehicle is None:
        raise AppError(404, "not_found")
    return vehicle


async def get_vehicle_detail(session: AsyncSession, vehicle_id: uuid.UUID) -> VehicleDetail:
    vehicle = await get_vehicle(session, vehicle_id)
    owner = await session.get(Client, vehicle.client_id)
    if owner is None:  # pragma: no cover - FK гарантирует наличие
        raise AppError(404, "not_found")
    return VehicleDetail(
        **to_read(vehicle).model_dump(),
        client=VehicleOwner(id=owner.id, full_name=owner.full_name, phone=owner.phone),
    )


async def list_vehicles(
    session: AsyncSession, client_id: uuid.UUID, include_archived: bool
) -> list[VehicleRead]:
    if await session.get(Client, client_id) is None:
        raise AppError(404, "not_found")
    stmt = select(Vehicle).where(Vehicle.client_id == client_id)
    if not include_archived:
        stmt = stmt.where(Vehicle.archived_at.is_(None))
    rows = await session.scalars(stmt.order_by(Vehicle.created_at, Vehicle.id))
    return [to_read(v) for v in rows]


async def _ensure_vin_free(
    session: AsyncSession, vin: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(Vehicle.id, Vehicle.client_id).where(
        Vehicle.vin == vin, Vehicle.archived_at.is_(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(Vehicle.id != exclude_id)
    row = (await session.execute(stmt.limit(1))).first()
    if row is not None:
        raise AppError(
            409,
            "duplicate_vin",
            {"vin": "duplicate"},
            {"existing_vehicle_id": str(row.id), "existing_client_id": str(row.client_id)},
        )


def _is_unique_violation(exc: IntegrityError) -> bool:
    pgcode = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return str(pgcode) == "23505"


async def _flush_checked(
    session: AsyncSession, vehicle: Vehicle, values: dict[str, Any] | None = None
) -> None:
    """Запись автомобиля под savepoint: параллельный запрос с тем же VIN, проскочивший
    `_ensure_vin_free`, упрётся в uq_vehicles_vin_active — отвечаем `duplicate_vin`
    с данными существующего автомобиля, а не общим `unique_violation`."""
    # После отката savepoint атрибуты объекта истекают — VIN и id запоминаются заранее.
    vin = (values or {}).get("vin") or vehicle.vin
    exclude_id = vehicle.id
    try:
        async with session.begin_nested():
            session.add(vehicle)
            for field, value in (values or {}).items():
                setattr(vehicle, field, value)
            await session.flush()
    except IntegrityError as exc:
        if _is_unique_violation(exc) and vin:
            await _ensure_vin_free(session, vin, exclude_id)
        raise


async def create_vehicle(
    session: AsyncSession,
    actor: User,
    client_id: uuid.UUID,
    data: VehicleCreate,
    client_info: ClientInfo,
) -> VehicleRead:
    owner = await session.get(Client, client_id)
    if owner is None:
        raise AppError(404, "not_found")
    if owner.archived_at is not None:
        raise AppError(409, "client_archived")
    if data.vin:
        await _ensure_vin_free(session, data.vin)
    vehicle = Vehicle(client_id=client_id, **data.model_dump())
    await _flush_checked(session, vehicle)
    write_audit(
        session,
        action="create",
        entity_type="vehicle",
        user_id=actor.id,
        entity_id=vehicle.id,
        changes={k: {"old": None, "new": v} for k, v in _snapshot(vehicle).items()},
        client=client_info,
    )
    await session.commit()
    return to_read(vehicle)


async def update_vehicle(
    session: AsyncSession,
    actor: User,
    vehicle_id: uuid.UUID,
    data: VehicleUpdate,
    client_info: ClientInfo,
) -> VehicleRead:
    vehicle = await get_vehicle(session, vehicle_id, for_update=True)
    values = data.model_dump(exclude_unset=True)
    new_vin = values.get("vin")
    if new_vin and new_vin != vehicle.vin and vehicle.archived_at is None:
        await _ensure_vin_free(session, new_vin, vehicle.id)
    old = _snapshot(vehicle)
    await _flush_checked(session, vehicle, values)
    changes = diff(old, _snapshot(vehicle))
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="vehicle",
            user_id=actor.id,
            entity_id=vehicle.id,
            changes=changes,
            client=client_info,
        )
    await session.commit()
    return to_read(vehicle)


async def set_archived(
    session: AsyncSession,
    actor: User,
    vehicle_id: uuid.UUID,
    archive: bool,
    client_info: ClientInfo,
) -> VehicleRead:
    vehicle = await get_vehicle(session, vehicle_id, for_update=True)
    if archive != (vehicle.archived_at is not None):
        if not archive and vehicle.vin:
            await _ensure_vin_free(session, vehicle.vin, vehicle.id)
        new_value: datetime | None = utcnow() if archive else None
        old_value = vehicle.archived_at
        await _flush_checked(session, vehicle, {"archived_at": new_value})
        write_audit(
            session,
            action="archive" if archive else "restore",
            entity_type="vehicle",
            user_id=actor.id,
            entity_id=vehicle.id,
            changes={
                "archived_at": {
                    "old": old_value.isoformat() if old_value else None,
                    "new": new_value.isoformat() if new_value else None,
                }
            },
            client=client_info,
        )
    await session.commit()
    return to_read(vehicle)
