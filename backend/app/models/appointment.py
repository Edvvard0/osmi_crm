import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id

# Статусы, при которых запись занимает пост (в ограничении `appointments_no_overlap`).
OCCUPYING_STATUSES = ("scheduled", "confirmed", "arrived")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_appointments_period"),
        CheckConstraint(
            "status IN ('scheduled','confirmed','arrived','no_show','cancelled')",
            name="ck_appointments_status",
        ),
        CheckConstraint("department IN ('service','detailing')", name="ck_appointments_department"),
        ExcludeConstraint(
            ("post_id", "="),
            (text("tstzrange(start_at, end_at, '[)')"), "&&"),
            name="appointments_no_overlap",
            using="gist",
            where=text("status IN ('scheduled','confirmed','arrived') AND post_id IS NOT NULL"),
        ),
        Index("ix_appointments_location_start", "location_id", "start_at"),
        Index("ix_appointments_client_id", "client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"))
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_posts.id"))
    department: Mapped[str] = mapped_column(String(10))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(15), server_default=text("'scheduled'"), default="scheduled"
    )
    comment: Mapped[str | None] = mapped_column(String(1000))
    # FK на work_orders добавит модуль 5.
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppointmentService(Base):
    __tablename__ = "appointment_services"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"), primary_key=True)
