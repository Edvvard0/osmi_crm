"""Запись (календарь): создание, перенос, смена статуса, выборка по диапазону дат точки."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Client, Location, Service, User, Vehicle, WorkPost
from app.models.appointment import OCCUPYING_STATUSES, Appointment, AppointmentService
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentUpdate,
    ClientRef,
    ServiceRef,
    VehicleRef,
)
from app.services.audit import ClientInfo, diff, write_audit

# Переходы статуса; arrived / no_show / cancelled — конечные.
TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"confirmed", "arrived", "no_show", "cancelled"}),
    "confirmed": frozenset({"arrived", "no_show", "cancelled"}),
}
TERMINAL = frozenset({"arrived", "no_show", "cancelled"})

MIN_DURATION = timedelta(minutes=15)
MAX_DURATION = timedelta(hours=12)
MAX_RANGE_DAYS = 31
_EXCLUSION_VIOLATION = "23P01"
_MIN_YEAR, _MAX_YEAR = 2000, 2100


# ---------------- вспомогательное ----------------


def _tz(loc: Location) -> ZoneInfo:
    return ZoneInfo(loc.timezone)


async def _get_location(
    session: AsyncSession, location_id: uuid.UUID, allowed: list[uuid.UUID]
) -> Location:
    """Чужая и несуществующая точка неразличимы: оба случая — 404."""
    if location_id not in allowed:
        raise AppError(404, "not_found")
    loc = await session.get(Location, location_id)
    if loc is None:  # pragma: no cover - allowed строится из существующих точек
        raise AppError(404, "not_found")
    return loc


async def _get_appointment(
    session: AsyncSession,
    appointment_id: uuid.UUID,
    allowed: list[uuid.UUID],
    *,
    for_update: bool = False,
) -> Appointment:
    appt = await session.get(Appointment, appointment_id, with_for_update=for_update)
    if appt is None or appt.location_id not in allowed:
        raise AppError(404, "not_found")
    return appt


def _aligned(d: datetime) -> bool:
    return d.second == 0 and d.microsecond == 0 and d.minute % 5 == 0


def _time_fields(start: datetime, end: datetime, tz: ZoneInfo) -> dict[str, str]:
    """Ошибки полей времени: диапазон лет, кратность 5 минутам, длительность 15 минут … 12 часов."""
    fields: dict[str, str] = {}
    if not _MIN_YEAR <= start.year <= _MAX_YEAR:
        fields["start_at"] = "invalid"
    if not _MIN_YEAR <= end.year <= _MAX_YEAR:
        fields["end_at"] = "invalid"
    if fields:
        return fields
    if not _aligned(start.astimezone(tz)):
        fields["start_at"] = "invalid"
    if not _aligned(end.astimezone(tz)) or not MIN_DURATION <= end - start <= MAX_DURATION:
        fields["end_at"] = "invalid"
    return fields


def _within_working_hours(start: datetime, end: datetime, loc: Location, tz: ZoneInfo) -> bool:
    ls, le = start.astimezone(tz), end.astimezone(tz)
    return ls.date() == le.date() and ls.time() >= loc.work_start and le.time() <= loc.work_end


async def _vehicle_ok(session: AsyncSession, client_id: uuid.UUID, vehicle_id: uuid.UUID) -> bool:
    vehicle = await session.get(Vehicle, vehicle_id)
    client = await session.get(Client, client_id)
    return (
        vehicle is not None
        and client is not None
        and vehicle.client_id == client.id
        and vehicle.archived_at is None
        and client.archived_at is None
    )


async def _post_ok(
    session: AsyncSession, post_id: uuid.UUID, location_id: uuid.UUID, department: str
) -> bool:
    post = await session.get(WorkPost, post_id)
    return (
        post is not None
        and post.location_id == location_id
        and post.is_active
        and post.department == department
    )


async def _services_ok(
    session: AsyncSession, service_ids: list[uuid.UUID], department: str
) -> bool:
    if not service_ids:
        return True
    found = await session.scalars(
        select(Service.id).where(
            Service.id.in_(service_ids),
            Service.is_active.is_(True),
            Service.department == department,
        )
    )
    return len(set(found)) == len(service_ids)


async def _service_ids(session: AsyncSession, appointment_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(AppointmentService.service_id).where(
            AppointmentService.appointment_id == appointment_id
        )
    )
    return list(rows)


def _unique(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


def _snapshot(appt: Appointment, service_ids: list[uuid.UUID]) -> dict[str, Any]:
    """Снимок для журнала: время в UTC, идентификаторы строками (JSON)."""
    return {
        "post_id": str(appt.post_id) if appt.post_id else None,
        "department": appt.department,
        "start_at": appt.start_at.astimezone(UTC).isoformat(),
        "end_at": appt.end_at.astimezone(UTC).isoformat(),
        "status": appt.status,
        "comment": appt.comment,
        "service_ids": sorted(str(i) for i in service_ids),
    }


# ---------------- чтение ----------------


async def _reads(session: AsyncSession, appts: list[Appointment]) -> list[AppointmentRead]:
    """Собирает ответы пачкой: услуги, клиенты, автомобили, пояса точек — по одному запросу."""
    if not appts:
        return []
    ids = [a.id for a in appts]
    services: dict[uuid.UUID, list[ServiceRef]] = {i: [] for i in ids}
    for aid, sid, name in await session.execute(
        select(AppointmentService.appointment_id, Service.id, Service.name)
        .join(Service, Service.id == AppointmentService.service_id)
        .where(AppointmentService.appointment_id.in_(ids))
        .order_by(Service.name, Service.id)
    ):
        services[aid].append(ServiceRef(id=sid, name=name))
    clients = {
        c.id: c
        for c in await session.scalars(
            select(Client).where(Client.id.in_({a.client_id for a in appts}))
        )
    }
    vehicles = {
        v.id: v
        for v in await session.scalars(
            select(Vehicle).where(Vehicle.id.in_({a.vehicle_id for a in appts}))
        )
    }
    zones = {
        loc.id: _tz(loc)
        for loc in await session.scalars(
            select(Location).where(Location.id.in_({a.location_id for a in appts}))
        )
    }
    out: list[AppointmentRead] = []
    for a in appts:
        tz, client, vehicle = zones[a.location_id], clients[a.client_id], vehicles[a.vehicle_id]
        refs = services[a.id]
        out.append(
            AppointmentRead(
                id=a.id,
                location_id=a.location_id,
                client_id=a.client_id,
                vehicle_id=a.vehicle_id,
                post_id=a.post_id,
                department=a.department,
                start_at=a.start_at.astimezone(tz),
                end_at=a.end_at.astimezone(tz),
                status=a.status,
                comment=a.comment,
                service_ids=[r.id for r in refs],
                services=refs,
                client=ClientRef(id=client.id, full_name=client.full_name, phone=client.phone),
                vehicle=VehicleRef(
                    id=vehicle.id,
                    make=vehicle.make,
                    model=vehicle.model,
                    plate_number=vehicle.plate_number,
                ),
                work_order_id=a.work_order_id,
                created_by=a.created_by,
                created_at=a.created_at.astimezone(tz),
                updated_at=a.updated_at.astimezone(tz),
            )
        )
    return out


async def _read_one(session: AsyncSession, appt: Appointment) -> AppointmentRead:
    return (await _reads(session, [appt]))[0]


async def list_appointments(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID,
    date_from: date,
    date_to: date,
    post_id: uuid.UUID | None,
    department: str | None,
    status: str | None,
    client_id: uuid.UUID | None,
) -> list[AppointmentRead]:
    loc = await _get_location(session, location_id, allowed)
    if (
        date_to < date_from
        or (date_to - date_from).days >= MAX_RANGE_DAYS
        or date_from.year < _MIN_YEAR
        or date_to.year > _MAX_YEAR
    ):
        raise AppError(422, "validation_error", {"date_to": "invalid"})
    tz = _tz(loc)
    lo = datetime.combine(date_from, time.min, tzinfo=tz)
    hi = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    stmt = select(Appointment).where(
        Appointment.location_id == loc.id, Appointment.start_at >= lo, Appointment.start_at < hi
    )
    if post_id is not None:
        stmt = stmt.where(Appointment.post_id == post_id)
    if department is not None:
        stmt = stmt.where(Appointment.department == department)
    if status is not None:
        stmt = stmt.where(Appointment.status == status)
    if client_id is not None:
        stmt = stmt.where(Appointment.client_id == client_id)
    rows = (await session.scalars(stmt.order_by(Appointment.start_at, Appointment.id))).all()
    return await _reads(session, list(rows))


async def get_appointment(
    session: AsyncSession, allowed: list[uuid.UUID], appointment_id: uuid.UUID
) -> AppointmentRead:
    return await _read_one(session, await _get_appointment(session, appointment_id, allowed))


# ---------------- запись изменений ----------------


async def _raise_busy(
    session: AsyncSession,
    *,
    post_id: uuid.UUID,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    exclude_id: uuid.UUID | None,
) -> None:
    """Находит конфликтующую запись отдельным запросом и отдаёт 409 post_busy."""
    stmt = select(Appointment).where(
        Appointment.post_id == post_id,
        Appointment.status.in_(OCCUPYING_STATUSES),
        Appointment.start_at < end,
        Appointment.end_at > start,
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    conflict = (await session.scalars(stmt.order_by(Appointment.start_at).limit(1))).first()
    details = None
    if conflict is not None:
        details = {
            "conflict_id": str(conflict.id),
            "start_at": conflict.start_at.astimezone(tz).isoformat(),
            "end_at": conflict.end_at.astimezone(tz).isoformat(),
        }
    raise AppError(409, "post_busy", details=details)


def _is_exclusion_violation(exc: IntegrityError) -> bool:
    pgcode = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return str(pgcode) == _EXCLUSION_VIOLATION


async def create_appointment(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    data: AppointmentCreate,
    client_info: ClientInfo,
) -> AppointmentRead:
    loc = await _get_location(session, data.location_id, allowed)
    tz = _tz(loc)
    service_ids = _unique(data.service_ids)
    fields: dict[str, str] = {}
    if not await _vehicle_ok(session, data.client_id, data.vehicle_id):
        fields["vehicle_id"] = "invalid"
    if data.post_id is not None and not await _post_ok(
        session, data.post_id, loc.id, data.department
    ):
        fields["post_id"] = "invalid"
    if not await _services_ok(session, service_ids, data.department):
        fields["service_ids"] = "invalid"
    fields |= _time_fields(data.start_at, data.end_at, tz)
    if fields:
        raise AppError(422, "validation_error", fields)
    if not _within_working_hours(data.start_at, data.end_at, loc, tz):
        raise AppError(422, "outside_working_hours")

    start, end = data.start_at.astimezone(UTC), data.end_at.astimezone(UTC)
    appt = Appointment(
        location_id=loc.id,
        client_id=data.client_id,
        vehicle_id=data.vehicle_id,
        post_id=data.post_id,
        department=data.department,
        start_at=start,
        end_at=end,
        status="scheduled",
        comment=data.comment or None,
        created_by=actor.id,
    )
    try:
        async with session.begin_nested():
            session.add(appt)
            await session.flush()
            session.add_all(
                AppointmentService(appointment_id=appt.id, service_id=sid) for sid in service_ids
            )
            await session.flush()
    except IntegrityError as exc:
        if not _is_exclusion_violation(exc) or data.post_id is None:
            raise
        await _raise_busy(
            session, post_id=data.post_id, start=start, end=end, tz=tz, exclude_id=None
        )
    await session.refresh(appt)
    write_audit(
        session,
        action="create",
        entity_type="appointment",
        user_id=actor.id,
        entity_id=appt.id,
        location_id=loc.id,
        changes={
            "client_id": {"old": None, "new": str(appt.client_id)},
            "vehicle_id": {"old": None, "new": str(appt.vehicle_id)},
            **{k: {"old": None, "new": v} for k, v in _snapshot(appt, service_ids).items()},
        },
        client=client_info,
    )
    await session.commit()
    return await _read_one(session, appt)


async def update_appointment(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    appointment_id: uuid.UUID,
    data: AppointmentUpdate,
    client_info: ClientInfo,
) -> AppointmentRead:
    appt = await _get_appointment(session, appointment_id, allowed, for_update=True)
    if appt.status in TERMINAL:
        raise AppError(409, "invalid_state")
    values = data.model_dump(exclude_unset=True)
    if not values:
        return await _read_one(session, appt)
    loc = await _get_location(session, appt.location_id, allowed)
    tz = _tz(loc)

    fields: dict[str, str] = {}
    times_given = "start_at" in values or "end_at" in values
    if times_given:
        # start_at и end_at передаются вместе.
        for name in ("start_at", "end_at"):
            if name not in values:
                fields[name] = "required"
    department = values.get("department", appt.department)
    post_id = values.get("post_id", appt.post_id)
    start = values["start_at"].astimezone(UTC) if "start_at" in values else appt.start_at
    end = values["end_at"].astimezone(UTC) if "end_at" in values else appt.end_at
    old_service_ids = await _service_ids(session, appt.id)
    service_ids = _unique(values["service_ids"]) if "service_ids" in values else old_service_ids

    if (
        post_id is not None
        and ("post_id" in values or "department" in values)
        and not await _post_ok(session, post_id, loc.id, department)
    ):
        fields["post_id"] = "invalid"
    if ("service_ids" in values or "department" in values) and not await _services_ok(
        session, service_ids, department
    ):
        fields["service_ids"] = "invalid"
    if times_given and not fields:
        fields |= _time_fields(start, end, tz)
    if fields:
        raise AppError(422, "validation_error", fields)
    if times_given and not _within_working_hours(start, end, loc, tz):
        raise AppError(422, "outside_working_hours")

    old = _snapshot(appt, old_service_ids)
    try:
        async with session.begin_nested():
            appt.post_id, appt.department = post_id, department
            appt.start_at, appt.end_at = start, end
            if "comment" in values:
                appt.comment = values["comment"] or None
            if "service_ids" in values and set(service_ids) != set(old_service_ids):
                await session.execute(
                    delete(AppointmentService).where(AppointmentService.appointment_id == appt.id)
                )
                session.add_all(
                    AppointmentService(appointment_id=appt.id, service_id=sid)
                    for sid in service_ids
                )
            await session.flush()
    except IntegrityError as exc:
        if not _is_exclusion_violation(exc) or post_id is None:
            raise
        await _raise_busy(
            session, post_id=post_id, start=start, end=end, tz=tz, exclude_id=appointment_id
        )
    await session.refresh(appt)
    changes = diff(old, _snapshot(appt, service_ids))
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="appointment",
            user_id=actor.id,
            entity_id=appt.id,
            location_id=appt.location_id,
            changes=changes,
            client=client_info,
        )
    await session.commit()
    return await _read_one(session, appt)


async def change_status(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    appointment_id: uuid.UUID,
    status: str,
    client_info: ClientInfo,
) -> AppointmentRead:
    appt = await _get_appointment(session, appointment_id, allowed, for_update=True)
    if status not in TRANSITIONS.get(appt.status, frozenset()):
        raise AppError(409, "invalid_transition")
    old = appt.status
    appt.status = status
    await session.flush()
    await session.refresh(appt)
    write_audit(
        session,
        action="status",
        entity_type="appointment",
        user_id=actor.id,
        entity_id=appt.id,
        location_id=appt.location_id,
        changes={"status": {"old": old, "new": status}},
        client=client_info,
    )
    await session.commit()
    return await _read_one(session, appt)
