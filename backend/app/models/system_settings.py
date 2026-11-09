import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SystemSetting(Base):
    """Системная настройка: значение проверяется схемой по ключу, по умолчанию — в коде."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
