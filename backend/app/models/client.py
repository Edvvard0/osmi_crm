import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("client_type IN ('person','company')", name="ck_clients_client_type"),
        CheckConstraint("inn ~ '^\\d{10}(\\d{2})?$'", name="ck_clients_inn"),
        CheckConstraint(
            "source IN ('walk_in','referral','online','ads','repeat','other')",
            name="ck_clients_source",
        ),
        CheckConstraint("discount_percent BETWEEN 0 AND 100", name="ck_clients_discount"),
        Index(
            "uq_clients_phone_active",
            "phone",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "ix_clients_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_clients_phone_trgm",
            "phone",
            postgresql_using="gin",
            postgresql_ops={"phone": "gin_trgm_ops"},
        ),
        Index(
            "ix_clients_company_name_trgm",
            "company_name",
            postgresql_using="gin",
            postgresql_ops={"company_name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    client_type: Mapped[str] = mapped_column(String(10))
    full_name: Mapped[str] = mapped_column(String(150))
    company_name: Mapped[str | None] = mapped_column(String(200))
    inn: Mapped[str | None] = mapped_column(String(12))
    phone: Mapped[str] = mapped_column(String(20))
    phone_extra: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))
    source: Mapped[str | None] = mapped_column(String(20))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default=text("0"), default=Decimal(0)
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("year BETWEEN 1950 AND 2100", name="ck_vehicles_year"),
        CheckConstraint("vin ~ '^[A-HJ-NPR-Z0-9]{17}$'", name="ck_vehicles_vin"),
        CheckConstraint("mileage >= 0", name="ck_vehicles_mileage"),
        Index(
            "uq_vehicles_vin_active",
            "vin",
            unique=True,
            postgresql_where=text("vin IS NOT NULL AND archived_at IS NULL"),
        ),
        Index("ix_vehicles_plate_number", "plate_number"),
        Index("ix_vehicles_client_id", "client_id"),
        Index(
            "ix_vehicles_plate_number_trgm",
            "plate_number",
            postgresql_using="gin",
            postgresql_ops={"plate_number": "gin_trgm_ops"},
        ),
        Index(
            "ix_vehicles_vin_trgm",
            "vin",
            postgresql_using="gin",
            postgresql_ops={"vin": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"))
    make: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    vin: Mapped[str | None] = mapped_column(String(17))
    plate_number: Mapped[str | None] = mapped_column(String(12))
    color: Mapped[str | None] = mapped_column(String(30))
    mileage: Mapped[int | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
