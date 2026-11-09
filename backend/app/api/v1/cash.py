import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import AllowedLocations, Client, Director, SessionDep, Staff
from app.schemas.cash import (
    CashKind,
    CashOperationPage,
    CashReport,
    ExpenseCancel,
    ExpenseCategoryCreate,
    ExpenseCategoryRead,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpensePage,
    ExpenseRead,
    PaymentCreate,
    PaymentMethod,
    PaymentRead,
    PaymentResult,
    RefundCreate,
)
from app.services import cash as svc
from app.services.cash_orders import order_read

router = APIRouter(tags=["cash"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


# ---------------- оплаты и возвраты ----------------


@router.post("/work-orders/{order_id}/payments", response_model=PaymentResult, status_code=201)
async def create_payment(
    order_id: uuid.UUID,
    data: PaymentCreate,
    response: Response,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> PaymentResult:
    payment, created = await svc.create_payment(session, actor, allowed, order_id, data, client)
    if not created:
        response.status_code = 200
    return PaymentResult(payment=payment, order=await order_read(session, actor, allowed, order_id))


@router.get("/work-orders/{order_id}/payments", response_model=list[PaymentRead])
async def list_payments(
    order_id: uuid.UUID, _: Staff, session: SessionDep, allowed: AllowedLocations
) -> list[PaymentRead]:
    return await svc.list_payments(session, allowed, order_id)


@router.post("/payments/{payment_id}/refund", response_model=PaymentResult, status_code=201)
async def refund_payment(
    payment_id: uuid.UUID,
    data: RefundCreate,
    response: Response,
    actor: Director,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> PaymentResult:
    payment, created = await svc.refund_payment(session, actor, payment_id, data, client)
    if not created:
        response.status_code = 200
    return PaymentResult(
        payment=payment, order=await order_read(session, actor, allowed, payment.work_order_id)
    )


# ---------------- категории расходов ----------------


@router.get("/expense-categories", response_model=list[ExpenseCategoryRead])
async def list_categories(
    _: Staff, session: SessionDep, include_inactive: bool = False
) -> list[ExpenseCategoryRead]:
    return await svc.list_categories(session, include_inactive)


@router.post("/expense-categories", response_model=ExpenseCategoryRead, status_code=201)
async def create_category(
    data: ExpenseCategoryCreate, actor: Director, session: SessionDep, client: Client
) -> ExpenseCategoryRead:
    return await svc.create_category(session, actor, data, client)


@router.patch("/expense-categories/{category_id}", response_model=ExpenseCategoryRead)
async def update_category(
    category_id: uuid.UUID,
    data: ExpenseCategoryUpdate,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> ExpenseCategoryRead:
    return await svc.update_category(session, actor, category_id, data, client)


# ---------------- расходы ----------------


@router.post("/expenses", response_model=ExpenseRead, status_code=201)
async def create_expense(
    data: ExpenseCreate,
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
) -> ExpenseRead:
    return await svc.create_expense(session, actor, allowed, data, client)


@router.get("/expenses", response_model=ExpensePage)
async def list_expenses(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    method: PaymentMethod | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_cancelled: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ExpensePage:
    return await svc.list_expenses(
        session,
        allowed,
        location_id=location_id,
        category_id=category_id,
        method=method,
        date_from=date_from,
        date_to=date_to,
        include_cancelled=include_cancelled,
        limit=limit,
        offset=offset,
    )


@router.post("/expenses/{expense_id}/cancel", response_model=ExpenseRead)
async def cancel_expense(
    expense_id: uuid.UUID,
    actor: Director,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
    data: ExpenseCancel | None = None,
) -> ExpenseRead:
    reason = data.reason if data else None
    return await svc.cancel_expense(session, actor, allowed, expense_id, reason, client)


# ---------------- кассовый отчёт ----------------


@router.get("/cash/report", response_model=CashReport)
async def cash_report(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> CashReport:
    return await svc.cash_report(
        session, allowed, location_id=location_id, date_from=date_from, date_to=date_to
    )


@router.get("/cash/operations", response_model=CashOperationPage)
async def cash_operations(
    _: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    kind: CashKind | None = None,
    method: PaymentMethod | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> CashOperationPage:
    return await svc.cash_operations(
        session,
        allowed,
        location_id=location_id,
        date_from=date_from,
        date_to=date_to,
        kind=kind,
        method=method,
        limit=limit,
        offset=offset,
    )
