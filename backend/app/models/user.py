import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("login ~ '^[a-z0-9._-]{3,50}$'", name="ck_users_login"),
        CheckConstraint("role IN ('mechanic','manager','director')", name="ck_users_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    login: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("0"), default=0
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserLocation(Base):
    __tablename__ = "user_locations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        Index(
            "ix_refresh_sessions_user_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
