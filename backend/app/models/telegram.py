import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"
    __table_args__ = (
        Index("ix_telegram_link_codes_user_created", "user_id", sql_text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"), default=True)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','sent','failed','skipped')", name="ck_notification_outbox_status"
        ),
        Index(
            "ix_notification_outbox_pending",
            "next_attempt_at",
            postgresql_where=sql_text("status = 'pending'"),
        ),
        Index("ix_notification_outbox_chat_status", "chat_id", "status"),
        Index(
            "notification_outbox_dedup",
            "dedup_key",
            unique=True,
            postgresql_where=sql_text("dedup_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(String(4096))
    status: Mapped[str] = mapped_column(
        String(10), server_default=sql_text("'pending'"), default="pending"
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=sql_text("0"), default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
    dedup_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
