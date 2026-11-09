import uuid
from datetime import datetime, time

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String, Time, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z0-9]{2,10}$'", name="ck_locations_code"),
        CheckConstraint("work_end > work_start", name="ck_locations_work_hours"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(
        String(64), server_default=text("'Europe/Moscow'"), default="Europe/Moscow"
    )
    work_start: Mapped[time] = mapped_column(Time, server_default=text("'09:00'"), default=time(9))
    work_end: Mapped[time] = mapped_column(Time, server_default=text("'21:00'"), default=time(21))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
