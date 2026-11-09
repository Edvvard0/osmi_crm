import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, User
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate
from app.services.audit import ClientInfo, diff, write_audit


def to_read(loc: Location) -> LocationRead:
    return LocationRead(
        id=loc.id, name=loc.name, address=loc.address, phone=loc.phone, is_active=loc.is_active
    )


def _snapshot(loc: Location) -> dict[str, object]:
    return {
        "name": loc.name,
        "address": loc.address,
        "phone": loc.phone,
        "is_active": loc.is_active,
    }


async def list_locations(session: AsyncSession, allowed: list[uuid.UUID]) -> list[LocationRead]:
    rows = await session.scalars(
        select(Location).where(Location.id.in_(allowed)).order_by(Location.name, Location.id)
    )
    return [to_read(r) for r in rows]


async def get_location(
    session: AsyncSession, location_id: uuid.UUID, allowed: list[uuid.UUID]
) -> Location:
    """Чужая и несуществующая точка неразличимы: оба случая — 404."""
    if location_id not in allowed:
        raise AppError(404, "not_found")
    loc = await session.get(Location, location_id)
    if loc is None:
        raise AppError(404, "not_found")
    return loc


async def _make_code(session: AsyncSession, name: str) -> str:
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:6]
    if len(base) < 2:
        base = "LOC"
    code, n = base, 1
    while await session.scalar(select(Location.id).where(Location.code == code)):
        n += 1
        code = f"{base}{n}"[:10]
    return code


async def create_location(
    session: AsyncSession, actor: User, data: LocationCreate, client: ClientInfo
) -> LocationRead:
    loc = Location(
        name=data.name,
        address=data.address,
        phone=data.phone,
        code=await _make_code(session, data.name),
    )
    session.add(loc)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="location",
        user_id=actor.id,
        entity_id=loc.id,
        location_id=loc.id,
        changes={k: {"old": None, "new": v} for k, v in _snapshot(loc).items()},
        client=client,
    )
    await session.commit()
    return to_read(loc)


async def update_location(
    session: AsyncSession,
    actor: User,
    location_id: uuid.UUID,
    data: LocationUpdate,
    client: ClientInfo,
) -> LocationRead:
    loc = await session.get(Location, location_id, with_for_update=True)
    if loc is None:
        raise AppError(404, "not_found")
    old = _snapshot(loc)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(loc, field, value)
    changes = diff(old, _snapshot(loc))
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="location",
            user_id=actor.id,
            entity_id=loc.id,
            location_id=loc.id,
            changes=changes,
            client=client,
        )
    await session.commit()
    return to_read(loc)
