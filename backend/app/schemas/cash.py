import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, PlainSerializer

from app.core.types import SafeText
from app.schemas.client import BlankToNone
from app.schemas.common import PatchBase, Strict
from app.schemas.work_order import WorkOrderRead

PaymentMethod = Literal["cash", "card", "transfer", "other"]
PaymentType = Literal["payment", "refund"]
CashKind = Literal["payment", "refund", "expense"]

METHOD_ORDER: tuple[str, ...] = ("cash", "card", "transfer", "other")

PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


def _dec2(value: Decimal) -> str:
    return f"{value:.2f}"


# В API деньги — строки с двумя знаками ("1500.00", "-250.00").
MoneyOut = Annotated[Decimal, PlainSerializer(_dec2, return_type=str)]


class UserRef(Strict):
    id: uuid.UUID
    full_name: str


class NameRef(Strict):
    id: uuid.UUID
    name: str


class OrderRef(Strict):
    id: uuid.UUID
    number: str


# ---------------- оплаты ----------------


class PaymentCreate(BlankToNone, Strict):
    blank_fields = frozenset({"comment"})

    amount: PositiveMoney
    method: PaymentMethod
    comment: SafeText(500) | None = None  # type: ignore[valid-type]
    client_request_id: uuid.UUID | None = None


class RefundCreate(Strict):
    amount: PositiveMoney | None = None
    comment: SafeText(500, 3)  # type: ignore[valid-type]
    client_request_id: uuid.UUID | None = None


class PaymentRead(Strict):
    id: uuid.UUID
    work_order_id: uuid.UUID
    order_number: str
    location_id: uuid.UUID
    payment_type: PaymentType
    amount: MoneyOut
    method: PaymentMethod
    paid_at: datetime
    refund_of_id: uuid.UUID | None
    refundable: MoneyOut | None
    comment: str | None
    accepted_by: UserRef
    created_at: datetime


class PaymentResult(Strict):
    payment: PaymentRead
    order: WorkOrderRead


# ---------------- расходы ----------------


class ExpenseCategoryRead(Strict):
    id: uuid.UUID
    name: str
    is_active: bool


class ExpenseCategoryCreate(Strict):
    name: SafeText(100, 1)  # type: ignore[valid-type]


class ExpenseCategoryUpdate(PatchBase):
    name: SafeText(100, 1) | None = None  # type: ignore[valid-type]
    is_active: bool | None = None


class ExpenseCreate(BlankToNone, Strict):
    blank_fields = frozenset({"description"})

    location_id: uuid.UUID
    category_id: uuid.UUID
    amount: PositiveMoney
    method: PaymentMethod
    expense_date: date
    description: SafeText(500) | None = None  # type: ignore[valid-type]


class ExpenseCancel(BlankToNone, Strict):
    blank_fields = frozenset({"reason"})

    reason: SafeText(500) | None = None  # type: ignore[valid-type]


class ExpenseRead(Strict):
    id: uuid.UUID
    location_id: uuid.UUID
    category: NameRef
    amount: MoneyOut
    method: PaymentMethod
    expense_date: date
    description: str | None
    created_by: UserRef
    created_at: datetime
    cancelled_at: datetime | None
    cancelled_by: UserRef | None


class ExpensePage(Strict):
    items: list[ExpenseRead]
    total: int
    total_amount: MoneyOut


# ---------------- касса ----------------


class CashOperation(Strict):
    kind: CashKind
    id: uuid.UUID
    at: datetime
    method: PaymentMethod
    amount: MoneyOut
    signed_amount: MoneyOut
    order: OrderRef | None
    category: NameRef | None
    comment: str | None
    user: UserRef
    is_cancelled: bool
    refundable: MoneyOut | None


class CashOperationPage(Strict):
    items: list[CashOperation]
    total: int


class MethodTotals(Strict):
    method: PaymentMethod
    received: MoneyOut
    refunded: MoneyOut
    net: MoneyOut


class MethodExpense(Strict):
    method: PaymentMethod
    total: MoneyOut


class CategoryExpense(Strict):
    category: NameRef
    total: MoneyOut


class CashReport(Strict):
    location_id: uuid.UUID
    date_from: date
    date_to: date
    timezone: str
    payments: list[MethodTotals]
    received_total: MoneyOut
    refunded_total: MoneyOut
    net_total: MoneyOut
    expenses_by_method: list[MethodExpense]
    expenses_by_category: list[CategoryExpense]
    expenses_total: MoneyOut
    cash_balance: MoneyOut
