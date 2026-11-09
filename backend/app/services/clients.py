import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Client, User, Vehicle
from app.schemas.client import ClientCreate, ClientDetail, ClientPage, ClientRead, ClientUpdate
from app.services.audit import ClientInfo, diff, write_audit
from app.services.search import clean_term, client_cond
from app.services.sessions import utcnow
from app.services.vehicles import to_read as vehicle_to_read

_FIELDS = (
    "client_type",
    "full_name",
    "company_name",
    "inn",
    "phone",
    "phone_extra",
    "email",
    "source",
    "discount_percent",
    "notes",
)


def to_read(client: Client, vehicles_count: int) -> ClientRead:
    return ClientRead(
        id=client.id,
        client_type=client.client_type,
        full_name=client.full_name,
        company_name=client.company_name,
        inn=client.inn,
        phone=client.phone,
        phone_extra=client.phone_extra,
        email=client.email,
        source=client.source,
        discount_percent=float(client.discount_percent),
        notes=client.notes,
        vehicles_count=vehicles_count,
        created_at=client.created_at,
        archived_at=client.archived_at,
    )


def _snapshot(client: Client) -> dict[str, Any]:
    snap = {f: getattr(client, f) for f in _FIELDS}
    snap["discount_percent"] = float(client.discount_percent)
    return snap


async def counts_map(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    result = dict.fromkeys(ids, 0)
    if ids:
        rows = await session.execute(
            select(Vehicle.client_id, func.count())
            .where(Vehicle.client_id.in_(ids), Vehicle.archived_at.is_(None))
            .group_by(Vehicle.client_id)
        )
        for cid, n in rows:
            result[cid] = n
    return result


async def read_client(session: AsyncSession, client: Client) -> ClientRead:
    return to_read(client, (await counts_map(session, [client.id]))[client.id])


async def get_client(
    session: AsyncSession, client_id: uuid.UUID, *, for_update: bool = False
) -> Client:
    client = await session.get(Client, client_id, with_for_update=for_update)
    if client is None:
        raise AppError(404, "not_found")
    return client


async def get_client_detail(session: AsyncSession, client_id: uuid.UUID) -> ClientDetail:
    client = await get_client(session, client_id)
    vehicles = (
        await session.scalars(
            select(Vehicle)
            .where(Vehicle.client_id == client_id, Vehicle.archived_at.is_(None))
            .order_by(Vehicle.created_at, Vehicle.id)
        )
    ).all()
    base = to_read(client, len(vehicles))
    return ClientDetail(**base.model_dump(), vehicles=[vehicle_to_read(v) for v in vehicles])


async def list_clients(
    session: AsyncSession,
    *,
    search: str | None,
    client_type: Literal["person", "company"] | None,
    source: str | None,
    archived: bool,
    limit: int,
    offset: int,
) -> ClientPage:
    conds: list[Any] = [
        Client.archived_at.is_not(None) if archived else Client.archived_at.is_(None)
    ]
    term = clean_term(search)
    if term:
        conds.append(client_cond(term))
    if client_type:
        conds.append(Client.client_type == client_type)
    if source:
        conds.append(Client.source == source)
    total = await session.scalar(select(func.count()).select_from(Client).where(*conds)) or 0
    rows = (
        await session.scalars(
            select(Client)
            .where(*conds)
            .order_by(Client.full_name, Client.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    counts = await counts_map(session, [c.id for c in rows])
    return ClientPage(items=[to_read(c, counts[c.id]) for c in rows], total=total)


async def _ensure_phone_free(
    session: AsyncSession, phone: str, exclude_id: uuid.UUID | None = None
) -> None:
    stmt = select(Client.id, Client.full_name).where(
        Client.phone == phone, Client.archived_at.is_(None)
    )
    if exclude_id is not None:
        stmt = stmt.where(Client.id != exclude_id)
    row = (await session.execute(stmt.limit(1))).first()
    if row is not None:
        raise AppError(
            409,
            "duplicate_phone",
            {"phone": "duplicate"},
            {"existing_id": str(row.id), "existing_name": row.full_name},
        )


async def create_client(
    session: AsyncSession, actor: User, data: ClientCreate, client_info: ClientInfo
) -> ClientRead:
    await _ensure_phone_free(session, data.phone)
    client = Client(**data.model_dump(), created_by=actor.id)
    session.add(client)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="client",
        user_id=actor.id,
        entity_id=client.id,
        changes={k: {"old": None, "new": v} for k, v in _snapshot(client).items()},
        client=client_info,
    )
    await session.commit()
    return to_read(client, 0)


async def update_client(
    session: AsyncSession,
    actor: User,
    client_id: uuid.UUID,
    data: ClientUpdate,
    client_info: ClientInfo,
) -> ClientRead:
    client = await get_client(session, client_id, for_update=True)
    values = data.model_dump(exclude_unset=True)
    new_phone = values.get("phone")
    if new_phone is not None and new_phone != client.phone and client.archived_at is None:
        await _ensure_phone_free(session, new_phone, client.id)
    old = _snapshot(client)
    for field, value in values.items():
        setattr(client, field, value)
    changes = diff(old, _snapshot(client))
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="client",
            user_id=actor.id,
            entity_id=client.id,
            changes=changes,
            client=client_info,
        )
    await session.commit()
    return await read_client(session, client)


async def set_archived(
    session: AsyncSession,
    actor: User,
    client_id: uuid.UUID,
    archive: bool,
    client_info: ClientInfo,
) -> ClientRead:
    client = await get_client(session, client_id, for_update=True)
    if archive != (client.archived_at is not None):
        if not archive:
            await _ensure_phone_free(session, client.phone, client.id)
        new_value: datetime | None = utcnow() if archive else None
        old_value = client.archived_at
        client.archived_at = new_value
        write_audit(
            session,
            action="archive" if archive else "restore",
            entity_type="client",
            user_id=actor.id,
            entity_id=client.id,
            changes={
                "archived_at": {
                    "old": old_value.isoformat() if old_value else None,
                    "new": new_value.isoformat() if new_value else None,
                }
            },
            client=client_info,
        )
    await session.commit()
    return await read_client(session, client)
