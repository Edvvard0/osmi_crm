"""События модуля 4 для уведомлений (api-contract-m7.md): сборка payload и публикация."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User, Vehicle
from app.models.appointment import Appointment, AppointmentService
from app.services.events import publish


async def publish_created(session: AsyncSession, appt: Appointment, actor: User) -> None:
    if not get_settings().telegram_enabled:
        return
    vehicle = await session.get(Vehicle, appt.vehicle_id)
    count = await session.scalar(
        select(func.count())
        .select_from(AppointmentService)
        .where(AppointmentService.appointment_id == appt.id)
    )
    await publish(
        session,
        "appointment.created",
        {
            "appointment_id": str(appt.id),
            "start_at": appt.start_at.isoformat(),
            "plate_number": vehicle.plate_number if vehicle else None,
            "make": vehicle.make if vehicle else None,
            "model": vehicle.model if vehicle else None,
            "services_count": count or 0,
            "created_by_name": actor.full_name,
        },
        location_id=appt.location_id,
        actor_id=actor.id,
    )


async def publish_no_show(session: AsyncSession, appt: Appointment, actor: User) -> None:
    if not get_settings().telegram_enabled:
        return
    vehicle = await session.get(Vehicle, appt.vehicle_id)
    await publish(
        session,
        "appointment.no_show",
        {
            "appointment_id": str(appt.id),
            "start_at": appt.start_at.isoformat(),
            "plate_number": vehicle.plate_number if vehicle else None,
        },
        location_id=appt.location_id,
        actor_id=actor.id,
        dedup_key=f"appointment.no_show:{appt.id}",
    )
