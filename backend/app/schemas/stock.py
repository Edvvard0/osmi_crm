import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, ConfigDict, Field, PlainSerializer

from app.core.types import SafeText, _must_be_str
from app.schemas.common import Strict

_DECIMAL = re.compile(r"^\d+(\.\d+)?$")


def _decimal_str(v: Any) -> str:
    """Числа в запросах — только строки вида «12.500» (без экспоненты, знака и JSON-чисел)."""
    s = _must_be_str(v).strip()
    if not _DECIMAL.fullmatch(s):
        raise ValueError("invalid_decimal")
    return s


def _dec2(value: Decimal) -> str:
    return f"{value:.2f}"


def _dec3(value: Decimal) -> str:
    return f"{value:.3f}"


# Вход
Qty3In = Annotated[
    Decimal,
    BeforeValidator(_decimal_str),
    Field(gt=0, max_digits=12, decimal_places=3),
]
Qty3ZeroIn = Annotated[
    Decimal,
    BeforeValidator(_decimal_str),
    Field(ge=0, max_digits=12, decimal_places=3),
]
MoneyIn = Annotated[
    Decimal,
    BeforeValidator(_decimal_str),
    Field(ge=0, max_digits=12, decimal_places=2),
]

# Выход: строки с фиксированным числом знаков
Money = Annotated[Decimal, PlainSerializer(_dec2, return_type=str)]
Qty3 = Annotated[Decimal, PlainSerializer(_dec3, return_type=str)]

MovementType = Literal[
    "receipt",
    "issue_to_order",
    "return_from_order",
    "write_off",
    "transfer_out",
    "transfer_in",
    "adjustment",
]
StockScope = Literal["stocked", "low", "all"]
StockSort = Literal["name", "sku", "quantity", "stock_value"]
SortDir = Literal["asc", "desc"]


class ReadBase(Strict):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


# ---------------- вход ----------------


class MinQuantityUpdate(Strict):
    min_quantity: Qty3ZeroIn


class StockReceiptLine(Strict):
    part_id: uuid.UUID
    quantity: Qty3In
    unit_cost: MoneyIn


class StockWriteOffLine(Strict):
    part_id: uuid.UUID
    quantity: Qty3In


class StockTransferLine(Strict):
    part_id: uuid.UUID
    quantity: Qty3In


class InventoryLine(Strict):
    part_id: uuid.UUID
    expected_quantity: Qty3ZeroIn
    actual_quantity: Qty3ZeroIn


class ReceiptCreate(Strict):
    location_id: uuid.UUID
    supplier: SafeText(200) | None = None  # type: ignore[valid-type]
    document_number: SafeText(50) | None = None  # type: ignore[valid-type]
    items: Annotated[list[StockReceiptLine], Field(min_length=1, max_length=100)]


class WriteOffCreate(Strict):
    location_id: uuid.UUID
    reason: SafeText(500, 3)  # type: ignore[valid-type]
    items: Annotated[list[StockWriteOffLine], Field(min_length=1, max_length=100)]


class TransferCreate(Strict):
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    comment: SafeText(500) | None = None  # type: ignore[valid-type]
    items: Annotated[list[StockTransferLine], Field(min_length=1, max_length=100)]


class InventoryCommit(Strict):
    location_id: uuid.UUID
    comment: SafeText(500) | None = None  # type: ignore[valid-type]
    items: Annotated[list[InventoryLine], Field(min_length=1, max_length=500)]


class ReverseCreate(Strict):
    reason: SafeText(500, 3)  # type: ignore[valid-type]


# ---------------- выход ----------------


class UserRef(ReadBase):
    id: uuid.UUID
    full_name: str


class PartBrief(ReadBase):
    id: uuid.UUID
    sku: str
    name: str
    brand: str | None
    barcode: str | None
    unit: str
    department: str
    sale_price: Money
    is_active: bool


class PartMini(ReadBase):
    id: uuid.UUID
    sku: str
    name: str
    unit: str


class WorkOrderRef(ReadBase):
    id: uuid.UUID
    number: str


class StockBalanceRead(Strict):
    location_id: uuid.UUID
    part: PartBrief
    quantity: Qty3
    min_quantity: Qty3
    avg_cost: Money
    stock_value: Money
    is_low: bool
    updated_at: datetime | None


class StockTotals(Strict):
    positions: int
    low_count: int
    stock_value: Money


class StockPage(Strict):
    items: list[StockBalanceRead]
    total: int
    totals: StockTotals


class StockMovementRead(Strict):
    id: uuid.UUID
    location_id: uuid.UUID
    part: PartMini
    movement_type: MovementType
    quantity: Qty3
    unit_cost: Money
    total: Money
    balance_after: Qty3
    work_order: WorkOrderRef | None
    related_movement_id: uuid.UUID | None
    reversed: bool
    supplier: str | None
    document_number: str | None
    reason: str | None
    created_by: UserRef
    created_at: datetime


class MovementPage(Strict):
    items: list[StockMovementRead]
    total: int


class MovementsOut(Strict):
    movements: list[StockMovementRead]


class TransferOut(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    out: list[StockMovementRead]
    in_: list[StockMovementRead] = Field(alias="in")


class InventoryOut(Strict):
    movements: list[StockMovementRead]
    skipped: int

