import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
)

from app.core.types import Money, SafeText, _clean_text, _must_be_str
from app.schemas.client import BlankToNone
from app.schemas.common import PatchBase, Strict

Department = Literal["service", "detailing"]
PartDepartment = Literal["service", "detailing", "both"]
ServiceUnit = Literal["pcs", "hour", "set", "sqm"]
PartUnit = Literal["pcs", "l", "ml", "kg", "g", "m", "set"]
PostType = Literal["lift", "diagnostics", "detailing_box", "wash", "other"]

SortOrder = Annotated[int, Field(ge=0, le=32767)]
Hours = Annotated[Decimal, Field(ge=0, max_digits=5, decimal_places=2)]
Duration = Annotated[int, Field(gt=0, le=10_080)]
# Артикулы, коды и штрихкоды: без пробелов внутри.
Code = Annotated[
    str,
    BeforeValidator(_must_be_str),
    AfterValidator(_clean_text),
    StringConstraints(min_length=1, max_length=20, pattern=r"^\S+$"),
]
Sku = Annotated[
    str,
    BeforeValidator(_must_be_str),
    AfterValidator(_clean_text),
    StringConstraints(min_length=1, max_length=50, pattern=r"^\S+$"),
]
Barcode = Sku


def _dec2(value: Decimal) -> str:
    return f"{value:.2f}"


# В API деньги и часы — строки с двумя знаками ("1500.00", "1.50").
DecimalOut = Annotated[Decimal, PlainSerializer(_dec2, return_type=str)]


class ReadBase(Strict):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# ---------------- категории ----------------


class CategoryCreate(Strict):
    name: SafeText(100, 1)  # type: ignore[valid-type]
    department: Department
    sort_order: SortOrder = 0


class CategoryUpdate(PatchBase):
    name: SafeText(100, 1) | None = None  # type: ignore[valid-type]
    sort_order: SortOrder | None = None
    is_active: bool | None = None


class CategoryRead(ReadBase):
    id: uuid.UUID
    name: str
    department: Department
    sort_order: int
    is_active: bool


# ---------------- услуги ----------------


class ServiceCreate(BlankToNone, Strict):
    blank_fields = frozenset({"description", "norm_hours"})

    category_id: uuid.UUID
    code: Code
    name: SafeText(200, 1)  # type: ignore[valid-type]
    description: SafeText(1000) | None = None  # type: ignore[valid-type]
    unit: ServiceUnit
    base_price: Money
    norm_hours: Hours | None = None
    duration_minutes: Duration


class ServiceUpdate(BlankToNone, PatchBase):
    blank_fields = ServiceCreate.blank_fields
    nullable_fields = frozenset({"description", "norm_hours"})

    name: SafeText(200, 1) | None = None  # type: ignore[valid-type]
    description: SafeText(1000) | None = None  # type: ignore[valid-type]
    unit: ServiceUnit | None = None
    base_price: Money | None = None
    norm_hours: Hours | None = None
    duration_minutes: Duration | None = None
    is_active: bool | None = None


class ServiceRead(ReadBase):
    id: uuid.UUID
    category_id: uuid.UUID
    code: str
    name: str
    description: str | None
    department: Department
    unit: ServiceUnit
    base_price: DecimalOut
    norm_hours: DecimalOut
    duration_minutes: int
    is_active: bool
    price: DecimalOut


class ServicePage(Strict):
    items: list[ServiceRead]
    total: int


# ---------------- цены по точкам ----------------


class PriceSet(Strict):
    price: Money


class ServicePriceRead(ReadBase):
    service_id: uuid.UUID
    location_id: uuid.UUID
    price: DecimalOut
    updated_at: datetime


# ---------------- посты ----------------


class PostCreate(Strict):
    name: SafeText(50, 1)  # type: ignore[valid-type]
    post_type: PostType
    department: Department
    sort_order: SortOrder = 0


class PostUpdate(PatchBase):
    name: SafeText(50, 1) | None = None  # type: ignore[valid-type]
    post_type: PostType | None = None
    department: Department | None = None
    sort_order: SortOrder | None = None
    is_active: bool | None = None


class PostRead(ReadBase):
    id: uuid.UUID
    location_id: uuid.UUID
    name: str
    post_type: PostType
    department: Department
    sort_order: int
    is_active: bool


# ---------------- запчасти ----------------


class PartCreate(BlankToNone, Strict):
    blank_fields = frozenset({"brand", "barcode"})

    sku: Sku
    name: SafeText(200, 1)  # type: ignore[valid-type]
    brand: SafeText(100) | None = None  # type: ignore[valid-type]
    barcode: Barcode | None = None
    unit: PartUnit
    department: PartDepartment
    sale_price: Money


class PartUpdate(BlankToNone, PatchBase):
    blank_fields = PartCreate.blank_fields
    nullable_fields = frozenset({"brand", "barcode"})

    name: SafeText(200, 1) | None = None  # type: ignore[valid-type]
    brand: SafeText(100) | None = None  # type: ignore[valid-type]
    barcode: Barcode | None = None
    unit: PartUnit | None = None
    department: PartDepartment | None = None
    sale_price: Money | None = None
    is_active: bool | None = None


class PartRead(ReadBase):
    id: uuid.UUID
    sku: str
    name: str
    brand: str | None
    barcode: str | None
    unit: PartUnit
    department: PartDepartment
    sale_price: DecimalOut
    is_active: bool


class PartPage(Strict):
    items: list[PartRead]
    total: int
