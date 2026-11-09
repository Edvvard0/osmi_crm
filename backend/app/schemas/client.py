import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, model_validator

from app.core.types import _CTRL, VIN, Phone, PlateNumber, SafeText, _must_be_str
from app.schemas.common import PatchBase, Strict

ClientType = Literal["person", "company"]
Source = Literal["walk_in", "referral", "online", "ads", "repeat", "other"]

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
_INN = r"^\d{10}(\d{2})?$"


def _email(v: str) -> str:
    v = v.strip()
    # Длина проверяется до регулярного выражения; управляющие символы и разметка запрещены.
    if len(v) > 254 or _CTRL.search(v) or not _EMAIL.fullmatch(v) or "<" in v or ">" in v:
        raise ValueError("invalid_email")
    return v.lower()


Email = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_email)]
Inn = Annotated[str, Field(pattern=_INN, max_length=12)]
Discount = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class BlankToNone(BaseModel):
    """Пустая строка в необязательном поле означает «нет значения»."""

    blank_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _blank(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: (None if k in cls.blank_fields and isinstance(v, str) and not v.strip() else v)
                for k, v in data.items()
            }
        return data


# ---------------- clients ----------------


class ClientCreate(BlankToNone, Strict):
    blank_fields = frozenset({"company_name", "inn", "phone_extra", "email", "source", "notes"})

    client_type: ClientType
    full_name: SafeText(150, 1)  # type: ignore[valid-type]
    company_name: SafeText(200) | None = None  # type: ignore[valid-type]
    inn: Inn | None = None
    phone: Phone
    phone_extra: Phone | None = None
    email: Email | None = None
    source: Source | None = None
    discount_percent: Discount = Decimal(0)
    notes: SafeText(2000) | None = None  # type: ignore[valid-type]


class ClientUpdate(BlankToNone, PatchBase):
    blank_fields = ClientCreate.blank_fields
    nullable_fields = frozenset({"company_name", "inn", "phone_extra", "email", "source", "notes"})

    client_type: ClientType | None = None
    full_name: SafeText(150, 1) | None = None  # type: ignore[valid-type]
    company_name: SafeText(200) | None = None  # type: ignore[valid-type]
    inn: Inn | None = None
    phone: Phone | None = None
    phone_extra: Phone | None = None
    email: Email | None = None
    source: Source | None = None
    discount_percent: Discount | None = None
    notes: SafeText(2000) | None = None  # type: ignore[valid-type]


# ---------------- vehicles ----------------


class VehicleCreate(BlankToNone, Strict):
    blank_fields = frozenset({"year", "vin", "plate_number", "color", "mileage", "notes"})

    make: SafeText(50, 1)  # type: ignore[valid-type]
    model: SafeText(50, 1)  # type: ignore[valid-type]
    year: Annotated[int, Field(ge=1950, le=2100)] | None = None
    vin: VIN | None = None
    plate_number: PlateNumber | None = None
    color: SafeText(30) | None = None  # type: ignore[valid-type]
    mileage: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    notes: SafeText(1000) | None = None  # type: ignore[valid-type]


class VehicleUpdate(BlankToNone, PatchBase):
    blank_fields = VehicleCreate.blank_fields
    nullable_fields = frozenset({"year", "vin", "plate_number", "color", "mileage", "notes"})

    make: SafeText(50, 1) | None = None  # type: ignore[valid-type]
    model: SafeText(50, 1) | None = None  # type: ignore[valid-type]
    year: Annotated[int, Field(ge=1950, le=2100)] | None = None
    vin: VIN | None = None
    plate_number: PlateNumber | None = None
    color: SafeText(30) | None = None  # type: ignore[valid-type]
    mileage: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    notes: SafeText(1000) | None = None  # type: ignore[valid-type]


class VehicleRead(Strict):
    id: uuid.UUID
    client_id: uuid.UUID
    make: str
    model: str
    year: int | None
    vin: str | None
    plate_number: str | None
    color: str | None
    mileage: int | None
    notes: str | None
    created_at: datetime
    archived_at: datetime | None


class VehicleOwner(Strict):
    id: uuid.UUID
    full_name: str
    phone: str


class VehicleDetail(VehicleRead):
    client: VehicleOwner


class ClientRead(Strict):
    id: uuid.UUID
    client_type: ClientType
    full_name: str
    company_name: str | None
    inn: str | None
    phone: str
    phone_extra: str | None
    email: str | None
    source: Source | None
    discount_percent: float
    notes: str | None
    vehicles_count: int
    created_at: datetime
    archived_at: datetime | None
    # Статистика по закрытым заказам (модуль 5), деньги — строками.
    orders_count: int = 0
    total_spent: str = "0.00"
    average_check: str = "0.00"
    last_visit_at: datetime | None = None


class ClientDetail(ClientRead):
    vehicles: list[VehicleRead]


class ClientPage(Strict):
    items: list[ClientRead]
    total: int


# ---------------- search ----------------


class SearchHit(Strict):
    type: Literal["client", "vehicle"]
    id: uuid.UUID
    title: str
    subtitle: str
    client_id: uuid.UUID
