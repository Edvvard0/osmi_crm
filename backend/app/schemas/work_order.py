"""Схемы модуля 5 (заказ-наряды). Деньги, часы и количества — только строки (на входе и выходе)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    Field,
    PlainSerializer,
)

from app.core.types import SafeText
from app.schemas.appointment import ClientRef, VehicleRef
from app.schemas.catalog import Department
from app.schemas.client import BlankToNone
from app.schemas.common import PatchBase, Strict

WorkOrderStatus = Literal[
    "new",
    "diagnostics",
    "awaiting_approval",
    "in_progress",
    "awaiting_parts",
    "quality_check",
    "ready",
    "closed",
    "cancelled",
]
WorkOrderDepartment = Literal["service", "detailing", "mixed"]
ItemStatus = Literal["pending", "in_progress", "paused", "done", "cancelled"]
PaymentStatus = Literal["unpaid", "partial", "paid", "refunded"]


def _str_only(v: Any) -> Any:
    """Числа JSON для денег/часов/количеств не принимаются: только строки."""
    if not isinstance(v, str):
        raise ValueError("must_be_string")
    return v.strip()


def _fmt(places: int) -> Any:
    return PlainSerializer(lambda v: f"{v:.{places}f}", return_type=str)


# Вход.
Money = Annotated[
    Decimal, BeforeValidator(_str_only), Field(ge=0, max_digits=12, decimal_places=2)
]
Hours = Annotated[Decimal, BeforeValidator(_str_only), Field(ge=0, max_digits=5, decimal_places=2)]
Qty2 = Annotated[Decimal, BeforeValidator(_str_only), Field(gt=0, max_digits=8, decimal_places=2)]
Qty3 = Annotated[Decimal, BeforeValidator(_str_only), Field(gt=0, max_digits=12, decimal_places=3)]
Percent = Annotated[
    Decimal, BeforeValidator(_str_only), Field(ge=0, le=100, max_digits=5, decimal_places=2)
]
# Выход.
Money2 = Annotated[Decimal, _fmt(2)]
Qty3Out = Annotated[Decimal, _fmt(3)]
Version = Annotated[int, Field(ge=1, le=2_147_483_647)]
Mileage = Annotated[int, Field(ge=0, le=10_000_000)]


# ---------------- вход: работы и запчасти ----------------


class NewItem(BlankToNone, Strict):
    """Каталожная работа (`service_id`) либо произвольная (`name`, `department`, `unit_price`)."""

    service_id: uuid.UUID | None = None
    name: SafeText(200, 1) | None = None  # type: ignore[valid-type]
    department: Department | None = None
    unit_price: Money | None = None
    quantity: Qty2 = Decimal("1.00")
    discount_percent: Percent = Decimal("0.00")
    norm_hours: Hours | None = None
    mechanic_id: uuid.UUID | None = None


class ItemCreate(NewItem):
    version: Version


class ItemUpdate(BlankToNone, PatchBase):
    nullable_fields = frozenset({"mechanic_id"})

    version: Version
    quantity: Qty2 | None = None
    discount_percent: Percent | None = None
    mechanic_id: uuid.UUID | None = None
    name: SafeText(200, 1) | None = None  # type: ignore[valid-type]
    unit_price: Money | None = None
    norm_hours: Hours | None = None
    sort_order: Annotated[int, Field(ge=0, le=32767)] | None = None


class NewPart(Strict):
    part_id: uuid.UUID | None = None
    name: SafeText(200, 1) | None = None  # type: ignore[valid-type]
    quantity: Qty3
    unit_price: Money | None = None
    part_request_id: uuid.UUID | None = None


class PartCreate(NewPart):
    version: Version


class PartUpdate(PatchBase):
    version: Version
    quantity: Qty3 | None = None
    unit_price: Money | None = None
    name: SafeText(200, 1) | None = None  # type: ignore[valid-type]


class VersionBody(Strict):
    version: Version


# ---------------- вход: заказ ----------------


class WorkOrderCreate(BlankToNone, Strict):
    blank_fields = frozenset({"complaint", "intake_notes"})

    location_id: uuid.UUID
    client_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None
    department: Department | None = None
    manager_id: uuid.UUID | None = None
    mileage_in: Mileage | None = None
    complaint: SafeText(2000) | None = None  # type: ignore[valid-type]
    intake_notes: SafeText(2000) | None = None  # type: ignore[valid-type]
    planned_ready_at: AwareDatetime | None = None
    discount_percent: Percent | None = None
    items: Annotated[list[NewItem], Field(max_length=100)] | None = None


class WorkOrderUpdate(BlankToNone, PatchBase):
    blank_fields = frozenset({"complaint", "intake_notes", "diagnosis"})
    nullable_fields = frozenset(
        {"mileage_in", "complaint", "intake_notes", "diagnosis", "planned_ready_at"}
    )

    version: Version
    mileage_in: Mileage | None = None
    complaint: SafeText(2000) | None = None  # type: ignore[valid-type]
    intake_notes: SafeText(2000) | None = None  # type: ignore[valid-type]
    diagnosis: SafeText(4000) | None = None  # type: ignore[valid-type]
    planned_ready_at: AwareDatetime | None = None
    discount_percent: Percent | None = None
    manager_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None


class StatusChangeBody(BlankToNone, Strict):
    blank_fields = frozenset({"comment", "cancel_reason"})

    version: Version
    status: WorkOrderStatus
    comment: SafeText(500) | None = None  # type: ignore[valid-type]
    cancel_reason: SafeText(500, 1) | None = None  # type: ignore[valid-type]
    force_close: bool = False  # модуль 9: закрытие без полной оплаты (директор)


class CommentCreate(Strict):
    text: SafeText(2000, 1)  # type: ignore[valid-type]
    item_id: uuid.UUID | None = None
    is_internal: bool = True


class EmptyBody(Strict):
    pass


# ---------------- выход ----------------


class UserRef(Strict):
    id: uuid.UUID
    full_name: str


class ClientFull(ClientRef):
    discount_percent: float


class VehicleFull(VehicleRef):
    year: int | None
    vin: str | None
    color: str | None
    mileage: int | None


class WorkOrderItemRead(Strict):
    id: uuid.UUID
    service_id: uuid.UUID | None
    name: str
    department: Department
    quantity: Money2
    unit_price: Money2
    discount_percent: Money2
    total: Money2
    norm_hours: Money2
    norm_hours_total: Money2
    mechanic: UserRef | None
    status: ItemStatus
    started_at: datetime | None
    finished_at: datetime | None
    actual_minutes: int
    sort_order: int


class WorkOrderPartRead(Strict):
    id: uuid.UUID
    part_id: uuid.UUID | None
    name: str
    sku: str | None
    unit: str | None
    quantity: Qty3Out
    unit_price: Money2
    total: Money2
    unit_cost: Money2 | None
    in_stock: Qty3Out | None
    added_by: UserRef
    created_at: datetime


class WorkOrderListItem(Strict):
    id: uuid.UUID
    number: str
    location_id: uuid.UUID
    status: WorkOrderStatus
    department: WorkOrderDepartment
    created_at: datetime
    planned_ready_at: datetime | None
    is_overdue: bool
    mileage_in: int | None
    client: ClientRef
    vehicle: VehicleRef
    manager: UserRef
    mechanics: list[UserRef]
    items_count: int
    items_done_count: int
    works_total: Money2
    parts_total: Money2
    discount_total: Money2
    total: Money2
    paid_total: Money2
    balance_due: Money2
    payment_status: PaymentStatus
    version: int


class WorkOrderRead(WorkOrderListItem):
    client: ClientFull  # type: ignore[assignment]
    vehicle: VehicleFull  # type: ignore[assignment]
    complaint: str | None
    intake_notes: str | None
    diagnosis: str | None
    discount_percent: Money2
    started_at: datetime | None
    ready_at: datetime | None
    closed_at: datetime | None
    cancel_reason: str | None
    appointment_id: uuid.UUID | None
    refunded_total: Money2  # модуль 9: сумма возвратов
    items: list[WorkOrderItemRead]
    parts: list[WorkOrderPartRead]
    allowed_transitions: list[WorkOrderStatus]
    updated_at: datetime


class WorkOrderPage(Strict):
    items: list[WorkOrderListItem]
    total: int


class StatusHistoryEntry(Strict):
    id: uuid.UUID
    from_status: WorkOrderStatus | None
    to_status: WorkOrderStatus
    changed_by: UserRef
    comment: str | None
    created_at: datetime


class CommentAuthor(UserRef):
    role: str


class WorkOrderCommentRead(Strict):
    id: uuid.UUID
    item_id: uuid.UUID | None
    author: CommentAuthor
    text: str
    is_internal: bool
    created_at: datetime


class BoardColumn(Strict):
    status: WorkOrderStatus
    total: int
    items: list[WorkOrderListItem]


class OrderBoard(Strict):
    columns: list[BoardColumn]


class OrderSummary(Strict):
    in_progress: int
    awaiting_parts: int
    ready: int
    overdue: int
    open_total: int
