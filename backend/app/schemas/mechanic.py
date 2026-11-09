"""Схемы модуля 6: рабочее место механика (api-contract-m6.md).

Дробные числа в API — строки; на входе лишние знаки после запятой -> 422.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, PlainSerializer

from app.core.types import SafeText, _must_be_str
from app.schemas.catalog import Department
from app.schemas.client import BlankToNone
from app.schemas.common import PatchBase, Strict
from app.schemas.work_order import WorkOrderRead

ItemStatus = Literal["pending", "in_progress", "paused", "done", "cancelled"]
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
PartRequestStatus = Literal["new", "approved", "rejected", "issued"]
Priority = Literal["low", "medium", "high"]
RecommendationStatus = Literal["open", "done", "declined"]
TaskScope = Literal["today", "open"]


def _out2(value: Decimal) -> str:
    return f"{value:.2f}"


def _out3(value: Decimal) -> str:
    return f"{value:.3f}"


Dec2 = Annotated[Decimal, PlainSerializer(_out2, return_type=str)]
Dec3 = Annotated[Decimal, PlainSerializer(_out3, return_type=str)]

_QTY3 = re.compile(r"^\d{1,9}(\.\d{1,3})?$")
_MONEY = re.compile(r"^\d{1,10}(\.\d{1,2})?$")


def _qty3(v: str) -> Decimal:
    if not _QTY3.fullmatch(v):
        raise ValueError("invalid_quantity")
    d = Decimal(v)
    if d <= 0:
        raise ValueError("invalid_quantity")
    return d


def _money(v: str) -> Decimal:
    if not _MONEY.fullmatch(v):
        raise ValueError("invalid_money")
    return Decimal(v)


# На входе — только строки ("0.500"); число JSON отклоняется.
Qty3 = Annotated[
    Decimal,
    BeforeValidator(lambda v: _qty3(_must_be_str(v))),
    PlainSerializer(_out3, return_type=str),
]
MoneyIn = Annotated[Decimal, BeforeValidator(lambda v: _money(_must_be_str(v)))]


def _not_blank(v: str) -> str:
    if not v.strip():
        raise ValueError("blank")
    return v


# ---------------- общие ссылки ----------------


class UserRef(Strict):
    id: uuid.UUID
    full_name: str


class VehicleRef(Strict):
    id: uuid.UUID
    make: str
    model: str
    plate_number: str | None


# ---------------- задачи механика ----------------


class TaskVehicle(Strict):
    id: uuid.UUID
    make: str
    model: str
    year: int | None
    plate_number: str | None
    color: str | None


class MechanicTask(Strict):
    item_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    order_status: WorkOrderStatus
    department: Department
    name: str
    quantity: Dec2
    norm_hours: Dec2
    status: ItemStatus
    worked_seconds: int
    running_since: datetime | None
    vehicle: TaskVehicle
    planned_ready_at: datetime | None
    is_overdue: bool
    can_start: bool
    finished_at: datetime | None


class TaskItemBrief(Strict):
    item_id: uuid.UUID
    name: str
    quantity: Dec2
    norm_hours: Dec2
    status: ItemStatus
    worked_seconds: int
    running_since: datetime | None


class MechanicComment(Strict):
    id: uuid.UUID
    item_id: uuid.UUID | None
    author: UserRef
    text: str
    created_at: datetime


class MechanicTaskDetail(MechanicTask):
    complaint: str | None
    intake_notes: str | None
    mileage_in: int | None
    my_items: list[TaskItemBrief]
    comments: list[MechanicComment]
    server_time: datetime


class TaskList(Strict):
    active: MechanicTask | None
    items: list[MechanicTask]
    server_time: datetime


class StartBody(Strict):
    pause_active: bool = False


class FinishBody(BlankToNone, Strict):
    blank_fields = frozenset({"comment"})

    comment: SafeText(1000) | None = None  # type: ignore[valid-type]


class StartResult(Strict):
    task: MechanicTask
    active: MechanicTask
    server_time: datetime


class PauseResult(Strict):
    task: MechanicTask
    active: None = None
    server_time: datetime


class FinishResult(Strict):
    task: MechanicTask
    order_status: WorkOrderStatus
    order_auto_moved: bool
    active: None = None
    server_time: datetime


class CommentCreate(Strict):
    text: Annotated[SafeText(2000, 1), AfterValidator(_not_blank)]  # type: ignore[valid-type]


# ---------------- заявки на запчасти ----------------


class PartBrief(Strict):
    id: uuid.UUID
    name: str
    sku: str


class PartRequestCreate(BlankToNone, Strict):
    blank_fields = frozenset({"description"})

    item_id: uuid.UUID
    part_id: uuid.UUID | None = None
    description: SafeText(500) | None = None  # type: ignore[valid-type]
    quantity: Qty3 = Decimal("1.000")


class PartRequestRead(Strict):
    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    item_id: uuid.UUID | None
    item_name: str | None
    part: PartBrief | None
    description: str
    quantity: Dec3
    unit: str | None
    status: PartRequestStatus
    reject_reason: str | None
    created_at: datetime
    handled_at: datetime | None


class PartRequestPage(Strict):
    items: list[PartRequestRead]
    total: int


class MechanicPart(Strict):
    id: uuid.UUID
    sku: str
    name: str
    brand: str | None
    unit: str


# ---------------- рекомендации ----------------


class MechanicRecommendationCreate(Strict):
    item_id: uuid.UUID
    text: Annotated[SafeText(1000, 1), AfterValidator(_not_blank)]  # type: ignore[valid-type]
    priority: Priority = "medium"


class RecommendationCreate(Strict):
    text: Annotated[SafeText(1000, 1), AfterValidator(_not_blank)]  # type: ignore[valid-type]
    priority: Priority
    work_order_id: uuid.UUID | None = None


class RecommendationUpdate(PatchBase):
    nullable_fields = frozenset({"work_order_id"})

    status: RecommendationStatus | None = None
    priority: Priority | None = None
    text: Annotated[SafeText(1000, 1), AfterValidator(_not_blank)] | None = None  # type: ignore[valid-type]
    work_order_id: uuid.UUID | None = None


class VehicleRecommendation(Strict):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    work_order_id: uuid.UUID | None
    work_order_number: str | None
    text: str
    priority: Priority
    status: RecommendationStatus
    created_by: UserRef
    created_at: datetime
    updated_at: datetime


# ---------------- заявки: менеджер / директор ----------------


class OrderBrief(Strict):
    id: uuid.UUID
    number: str
    status: WorkOrderStatus
    version: int


class PartFull(Strict):
    id: uuid.UUID
    name: str
    sku: str
    unit: str
    sale_price: Dec2
    in_stock: Dec3 | None


class PartRequestFull(Strict):
    id: uuid.UUID
    location_id: uuid.UUID
    order: OrderBrief
    vehicle: VehicleRef
    item_id: uuid.UUID | None
    item_name: str | None
    mechanic: UserRef
    part: PartFull | None
    description: str
    quantity: Dec3
    status: PartRequestStatus
    reject_reason: str | None
    handled_by: UserRef | None
    handled_at: datetime | None
    created_at: datetime


class PartRequestFullPage(Strict):
    items: list[PartRequestFull]
    total: int


class PartRequestSummary(Strict):
    new: int
    approved: int


class PartApproveBody(Strict):
    part_id: uuid.UUID | None = None


class PartRejectBody(Strict):
    reason: Annotated[SafeText(500, 1), AfterValidator(_not_blank)]  # type: ignore[valid-type]


class PartIssueBody(Strict):
    version: Annotated[int, Field(ge=1, le=2_147_483_647)]
    part_id: uuid.UUID | None = None
    quantity: Qty3 | None = None
    unit_price: MoneyIn | None = None


class PartIssueResult(Strict):
    request: PartRequestFull
    order: WorkOrderRead


class ReopenBody(Strict):
    version: Annotated[int, Field(ge=1, le=2_147_483_647)]
