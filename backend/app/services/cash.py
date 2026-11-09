"""Касса: оплаты и возвраты по заказам, расходы, категории расходов, кассовый отчёт и операции."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, Role, User
from app.models.cash import Expense, ExpenseCategory, Payment
from app.models.work_order import WorkOrder
from app.schemas.cash import (
    METHOD_ORDER,
    CashOperation,
    CashOperationPage,
    CashReport,
    CategoryExpense,
    ExpenseCategoryCreate,
    ExpenseCategoryRead,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpensePage,
    ExpenseRead,
    MethodExpense,
    MethodTotals,
    NameRef,
    OrderRef,
    PaymentCreate,
    PaymentRead,
    RefundCreate,
    UserRef,
)
from app.services import events
from app.services.audit import ClientInfo, diff, write_audit
from app.services.payment_status import recalc_payment_status

_ZERO = Decimal("0.00")
MANAGER_BACKDATE_DAYS = 3
MAX_EXPENSES_DAYS = 366
MAX_REPORT_DAYS = 92


def _m(value: Decimal) -> str:
    return f"{value:.2f}"


def _tz(loc: Location) -> ZoneInfo:
    return ZoneInfo(loc.timezone)


def _is_director(actor: User) -> bool:
    return actor.role == Role.director


async def _get_location(
    session: AsyncSession, location_id: uuid.UUID, allowed: list[uuid.UUID]
) -> Location:
    """Чужая и несуществующая точка неразличимы: оба случая — 404."""
    if location_id not in allowed:
        raise AppError(404, "not_found")
    loc = await session.get(Location, location_id)
    if loc is None:  # pragma: no cover - allowed строится из существующих точек
        raise AppError(404, "not_found")
    return loc


async def _zones(session: AsyncSession, location_ids: set[uuid.UUID]) -> dict[uuid.UUID, ZoneInfo]:
    if not location_ids:
        return {}
    rows = await session.execute(
        select(Location.id, Location.timezone).where(Location.id.in_(location_ids))
    )
    return {i: ZoneInfo(tz) for i, tz in rows}


async def _users(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, UserRef]:
    real = {i for i in ids if i is not None}
    if not real:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(real)))
    return {i: UserRef(id=i, full_name=n) for i, n in rows}


async def _order_numbers(
    session: AsyncSession, order_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not order_ids:
        return {}
    rows = await session.execute(
        select(WorkOrder.id, WorkOrder.number).where(WorkOrder.id.in_(order_ids))
    )
    return {i: n for i, n in rows}


# ---------------- оплаты: чтение ----------------


async def _refundables(session: AsyncSession, payments: list[Payment]) -> dict[uuid.UUID, Decimal]:
    """Остаток к возврату по каждому платежу типа `payment`."""
    ids = [p.id for p in payments if p.payment_type == "payment"]
    if not ids:
        return {}
    rows = await session.execute(
        select(Payment.refund_of_id, func.sum(Payment.amount))
        .where(Payment.refund_of_id.in_(ids))
        .group_by(Payment.refund_of_id)
    )
    refunded = {i: Decimal(s) for i, s in rows}
    return {p.id: p.amount - refunded.get(p.id, _ZERO) for p in payments if p.id in ids}


async def payment_reads(session: AsyncSession, payments: list[Payment]) -> list[PaymentRead]:
    if not payments:
        return []
    refundable = await _refundables(session, payments)
    zones = await _zones(session, {p.location_id for p in payments})
    users = await _users(session, {p.accepted_by for p in payments})
    numbers = await _order_numbers(session, {p.work_order_id for p in payments})
    out: list[PaymentRead] = []
    for p in payments:
        tz = zones[p.location_id]
        out.append(
            PaymentRead(
                id=p.id,
                work_order_id=p.work_order_id,
                order_number=numbers[p.work_order_id],
                location_id=p.location_id,
                payment_type=p.payment_type,  # type: ignore[arg-type]
                amount=p.amount,
                method=p.method,  # type: ignore[arg-type]
                paid_at=p.paid_at.astimezone(tz),
                refund_of_id=p.refund_of_id,
                refundable=refundable.get(p.id) if p.payment_type == "payment" else None,
                comment=p.comment,
                accepted_by=users[p.accepted_by],
                created_at=p.created_at.astimezone(tz),
            )
        )
    return out


async def _lock_order(
    session: AsyncSession, allowed: list[uuid.UUID], order_id: uuid.UUID
) -> WorkOrder:
    order = await session.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None or order.location_id not in allowed:
        raise AppError(404, "not_found")
    return order


async def _by_request_id(
    session: AsyncSession, user_id: uuid.UUID, request_id: uuid.UUID | None
) -> Payment | None:
    if request_id is None:
        return None
    return await session.scalar(
        select(Payment).where(
            Payment.accepted_by == user_id, Payment.client_request_id == request_id
        )
    )


async def list_payments(
    session: AsyncSession, allowed: list[uuid.UUID], order_id: uuid.UUID
) -> list[PaymentRead]:
    order = await session.get(WorkOrder, order_id)
    if order is None or order.location_id not in allowed:
        raise AppError(404, "not_found")
    rows = await session.scalars(
        select(Payment)
        .where(Payment.work_order_id == order.id)
        .order_by(Payment.paid_at, Payment.created_at, Payment.id)
    )
    return await payment_reads(session, list(rows))


# ---------------- оплаты: запись ----------------


async def create_payment(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    data: PaymentCreate,
    client: ClientInfo,
) -> tuple[PaymentRead, bool]:
    """Возвращает (платёж, created); `created = False` — повтор по `client_request_id`."""
    order = await _lock_order(session, allowed, order_id)
    existing = await _by_request_id(session, actor.id, data.client_request_id)
    if existing is not None:
        if existing.work_order_id != order.id or existing.payment_type != "payment":
            raise AppError(409, "conflict")
        return (await payment_reads(session, [existing]))[0], False
    if order.status == "cancelled":
        raise AppError(409, "invalid_state")
    balance_due = max(order.total - order.paid_total, _ZERO)
    if balance_due == 0:
        raise AppError(409, "nothing_to_pay")
    if data.amount > balance_due:
        raise AppError(409, "overpayment", details={"balance_due": _m(balance_due)})
    payment = Payment(
        work_order_id=order.id,
        location_id=order.location_id,
        payment_type="payment",
        amount=data.amount,
        method=data.method,
        paid_at=datetime.now(UTC),
        comment=data.comment,
        accepted_by=actor.id,
        client_request_id=data.client_request_id,
    )
    session.add(payment)
    await session.flush()
    await recalc_payment_status(session, order)
    write_audit(
        session,
        action="create",
        entity_type="payment",
        user_id=actor.id,
        entity_id=payment.id,
        location_id=order.location_id,
        changes={
            "amount": _m(data.amount),
            "method": data.method,
            "order_number": order.number,
            "order_id": str(order.id),
        },
        client=client,
    )
    await session.flush()
    await session.refresh(payment)
    await session.commit()
    return (await payment_reads(session, [payment]))[0], True


async def refund_payment(
    session: AsyncSession,
    actor: User,
    payment_id: uuid.UUID,
    data: RefundCreate,
    client: ClientInfo,
) -> tuple[PaymentRead, bool]:
    """Возврат по платежу (только директор — проверяется в роутере)."""
    src = await session.get(Payment, payment_id)
    if src is None:
        raise AppError(404, "not_found")
    order = await _lock_order(session, [src.location_id], src.work_order_id)
    existing = await _by_request_id(session, actor.id, data.client_request_id)
    if existing is not None:
        if existing.refund_of_id != src.id:
            raise AppError(409, "conflict")
        return (await payment_reads(session, [existing]))[0], False
    if src.payment_type != "payment":
        raise AppError(409, "invalid_state")
    refundable = (await _refundables(session, [src]))[src.id]
    amount = data.amount if data.amount is not None else refundable
    if amount <= 0 or amount > refundable:
        raise AppError(409, "refund_exceeds_payment", details={"refundable": _m(refundable)})
    refund = Payment(
        work_order_id=order.id,
        location_id=order.location_id,
        payment_type="refund",
        amount=amount,
        method=src.method,
        paid_at=datetime.now(UTC),
        refund_of_id=src.id,
        comment=data.comment,
        accepted_by=actor.id,
        client_request_id=data.client_request_id,
    )
    session.add(refund)
    await session.flush()
    await recalc_payment_status(session, order)
    write_audit(
        session,
        action="refund",
        entity_type="payment",
        user_id=actor.id,
        entity_id=refund.id,
        location_id=order.location_id,
        changes={
            "amount": _m(amount),
            "refund_of_id": str(src.id),
            "reason": data.comment,
            "order_id": str(order.id),
        },
        client=client,
    )
    loc = await session.get(Location, order.location_id)
    await events.publish(
        session,
        "payment.refund",
        {
            "order_number": order.number,
            "amount": _m(amount),
            "method": src.method,
            "location_name": loc.name if loc else "",
            "user_name": actor.full_name,
            "reason": data.comment,
        },
        location_id=order.location_id,
        actor_id=actor.id,
        dedup_key=f"payment.refund:{refund.id}",
    )
    await session.flush()
    await session.refresh(refund)
    await session.commit()
    return (await payment_reads(session, [refund]))[0], True


# ---------------- категории расходов ----------------


def _cat_read(c: ExpenseCategory) -> ExpenseCategoryRead:
    return ExpenseCategoryRead(id=c.id, name=c.name, is_active=c.is_active)


async def list_categories(
    session: AsyncSession, include_inactive: bool
) -> list[ExpenseCategoryRead]:
    stmt = select(ExpenseCategory).order_by(ExpenseCategory.name, ExpenseCategory.id)
    if not include_inactive:
        stmt = stmt.where(ExpenseCategory.is_active.is_(True))
    return [_cat_read(c) for c in await session.scalars(stmt)]


async def _name_taken(session: AsyncSession, name: str, exclude: uuid.UUID | None = None) -> bool:
    # сравнение в Python: lower() в PostgreSQL зависит от локали БД и не гарантирует кириллицу
    rows = (await session.execute(select(ExpenseCategory.id, ExpenseCategory.name))).all()
    key = name.casefold()
    return any(i != exclude and n.casefold() == key for i, n in rows)


async def create_category(
    session: AsyncSession, actor: User, data: ExpenseCategoryCreate, client: ClientInfo
) -> ExpenseCategoryRead:
    if await _name_taken(session, data.name):
        raise AppError(409, "unique_violation")
    cat = ExpenseCategory(name=data.name)
    session.add(cat)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="expense_category",
        user_id=actor.id,
        entity_id=cat.id,
        changes={"name": cat.name},
        client=client,
    )
    await session.commit()
    return _cat_read(cat)


async def update_category(
    session: AsyncSession,
    actor: User,
    category_id: uuid.UUID,
    data: ExpenseCategoryUpdate,
    client: ClientInfo,
) -> ExpenseCategoryRead:
    cat = await session.get(ExpenseCategory, category_id, with_for_update=True)
    if cat is None:
        raise AppError(404, "not_found")
    old = {"name": cat.name, "is_active": cat.is_active}
    if data.name is not None and data.name != cat.name:
        if await _name_taken(session, data.name, cat.id):
            raise AppError(409, "unique_violation")
        cat.name = data.name
    if data.is_active is not None:
        cat.is_active = data.is_active
    changes = diff(old, {"name": cat.name, "is_active": cat.is_active})
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="expense_category",
            user_id=actor.id,
            entity_id=cat.id,
            changes=changes,
            client=client,
        )
    await session.commit()
    return _cat_read(cat)


# ---------------- расходы ----------------


async def _expense_reads(session: AsyncSession, items: list[Expense]) -> list[ExpenseRead]:
    if not items:
        return []
    zones = await _zones(session, {e.location_id for e in items})
    users = await _users(session, {e.created_by for e in items} | {e.cancelled_by for e in items})
    cats = {
        c.id: NameRef(id=c.id, name=c.name)
        for c in await session.scalars(
            select(ExpenseCategory).where(ExpenseCategory.id.in_({e.category_id for e in items}))
        )
    }
    out: list[ExpenseRead] = []
    for e in items:
        tz = zones[e.location_id]
        out.append(
            ExpenseRead(
                id=e.id,
                location_id=e.location_id,
                category=cats[e.category_id],
                amount=e.amount,
                method=e.method,  # type: ignore[arg-type]
                expense_date=e.expense_date,
                description=e.description,
                created_by=users[e.created_by],
                created_at=e.created_at.astimezone(tz),
                cancelled_at=e.cancelled_at.astimezone(tz) if e.cancelled_at else None,
                cancelled_by=users[e.cancelled_by] if e.cancelled_by else None,
            )
        )
    return out


async def create_expense(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    data: ExpenseCreate,
    client: ClientInfo,
) -> ExpenseRead:
    loc = await _get_location(session, data.location_id, allowed)
    today = datetime.now(_tz(loc)).date()
    if data.expense_date > today:
        raise AppError(422, "validation_error", {"expense_date": "future"})
    oldest = today - timedelta(days=MANAGER_BACKDATE_DAYS)
    if not _is_director(actor) and data.expense_date < oldest:
        raise AppError(422, "validation_error", {"expense_date": "too_old"})
    cat = await session.get(ExpenseCategory, data.category_id)
    if cat is None or not cat.is_active:
        raise AppError(422, "validation_error", {"category_id": "invalid"})
    exp = Expense(
        location_id=loc.id,
        category_id=cat.id,
        amount=data.amount,
        method=data.method,
        expense_date=data.expense_date,
        description=data.description,
        created_by=actor.id,
    )
    session.add(exp)
    await session.flush()
    write_audit(
        session,
        action="create",
        entity_type="expense",
        user_id=actor.id,
        entity_id=exp.id,
        location_id=loc.id,
        changes={
            "amount": _m(data.amount),
            "method": exp.method,
            "category_id": str(cat.id),
            "expense_date": exp.expense_date.isoformat(),
            "description": exp.description,
        },
        client=client,
    )
    await session.flush()
    await session.refresh(exp)
    await session.commit()
    return (await _expense_reads(session, [exp]))[0]


def _check_period(date_from: date, date_to: date, max_days: int) -> None:
    if date_to < date_from or (date_to - date_from).days + 1 > max_days:
        raise AppError(422, "validation_error", {"date_to": "invalid"})


async def list_expenses(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
    method: str | None,
    date_from: date | None,
    date_to: date | None,
    include_cancelled: bool,
    limit: int,
    offset: int,
) -> ExpensePage:
    if location_id is not None:
        await _get_location(session, location_id, allowed)
        locs = [location_id]
    else:
        locs = allowed
    if date_from is not None and date_to is not None:
        _check_period(date_from, date_to, MAX_EXPENSES_DAYS)
    conds: list[Any] = [Expense.location_id.in_(locs)]
    if category_id is not None:
        conds.append(Expense.category_id == category_id)
    if method is not None:
        conds.append(Expense.method == method)
    if date_from is not None:
        conds.append(Expense.expense_date >= date_from)
    if date_to is not None:
        conds.append(Expense.expense_date <= date_to)
    list_conds = list(conds)
    if not include_cancelled:
        list_conds.append(Expense.cancelled_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(Expense).where(*list_conds))
    total_amount = await session.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            *conds, Expense.cancelled_at.is_(None)
        )
    )
    rows = await session.scalars(
        select(Expense)
        .where(*list_conds)
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc(), Expense.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return ExpensePage(
        items=await _expense_reads(session, list(rows)),
        total=int(total or 0),
        total_amount=Decimal(total_amount or 0),
    )


async def cancel_expense(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    expense_id: uuid.UUID,
    reason: str | None,
    client: ClientInfo,
) -> ExpenseRead:
    exp = await session.get(Expense, expense_id, with_for_update=True)
    if exp is None or exp.location_id not in allowed:
        raise AppError(404, "not_found")
    if exp.cancelled_at is not None:
        raise AppError(409, "invalid_state")
    exp.cancelled_at = datetime.now(UTC)
    exp.cancelled_by = actor.id
    write_audit(
        session,
        action="update",
        entity_type="expense",
        user_id=actor.id,
        entity_id=exp.id,
        location_id=exp.location_id,
        changes={"cancelled_at": exp.cancelled_at.isoformat(), "reason": reason},
        client=client,
    )
    await session.commit()
    return (await _expense_reads(session, [exp]))[0]


# ---------------- кассовый отчёт и операции ----------------


def _bounds(
    loc: Location, date_from: date | None, date_to: date | None
) -> tuple[date, date, datetime, datetime]:
    tz = _tz(loc)
    start = date_from or datetime.now(tz).date()
    end = date_to or start
    _check_period(start, end, MAX_REPORT_DAYS)
    lo = datetime.combine(start, time.min, tzinfo=tz)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    return start, end, lo, hi


async def cash_report(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> CashReport:
    if location_id is None:
        raise AppError(422, "validation_error", {"location_id": "required"})
    loc = await _get_location(session, location_id, allowed)
    start, end, lo, hi = _bounds(loc, date_from, date_to)

    received = dict.fromkeys(METHOD_ORDER, _ZERO)
    refunded = dict.fromkeys(METHOD_ORDER, _ZERO)
    for method, ptype, total in await session.execute(
        select(Payment.method, Payment.payment_type, func.sum(Payment.amount))
        .where(Payment.location_id == loc.id, Payment.paid_at >= lo, Payment.paid_at < hi)
        .group_by(Payment.method, Payment.payment_type)
    ):
        (received if ptype == "payment" else refunded)[method] = Decimal(total)

    exp_where = (
        Expense.location_id == loc.id,
        Expense.expense_date >= start,
        Expense.expense_date <= end,
        Expense.cancelled_at.is_(None),
    )
    exp_method = dict.fromkeys(METHOD_ORDER, _ZERO)
    for method, total in await session.execute(
        select(Expense.method, func.sum(Expense.amount)).where(*exp_where).group_by(Expense.method)
    ):
        exp_method[method] = Decimal(total)
    by_cat = [
        CategoryExpense(category=NameRef(id=cid, name=name), total=Decimal(total))
        for cid, name, total in await session.execute(
            select(ExpenseCategory.id, ExpenseCategory.name, func.sum(Expense.amount))
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(*exp_where)
            .group_by(ExpenseCategory.id, ExpenseCategory.name)
            .order_by(ExpenseCategory.name)
        )
    ]
    received_total = sum(received.values(), _ZERO)
    refunded_total = sum(refunded.values(), _ZERO)
    expenses_total = sum(exp_method.values(), _ZERO)
    return CashReport(
        location_id=loc.id,
        date_from=start,
        date_to=end,
        timezone=loc.timezone,
        payments=[
            MethodTotals(
                method=m,  # type: ignore[arg-type]
                received=received[m],
                refunded=refunded[m],
                net=received[m] - refunded[m],
            )
            for m in METHOD_ORDER
        ],
        received_total=received_total,
        refunded_total=refunded_total,
        net_total=received_total - refunded_total,
        expenses_by_method=[
            MethodExpense(method=m, total=exp_method[m])  # type: ignore[arg-type]
            for m in METHOD_ORDER
        ],
        expenses_by_category=by_cat,
        expenses_total=expenses_total,
        cash_balance=received["cash"] - refunded["cash"] - exp_method["cash"],
    )


async def cash_operations(
    session: AsyncSession,
    allowed: list[uuid.UUID],
    *,
    location_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    kind: str | None,
    method: str | None,
    limit: int,
    offset: int,
) -> CashOperationPage:
    if location_id is None:
        raise AppError(422, "validation_error", {"location_id": "required"})
    loc = await _get_location(session, location_id, allowed)
    start, end, lo, hi = _bounds(loc, date_from, date_to)

    pay_q = select(
        Payment.payment_type.label("kind"),
        Payment.id.label("id"),
        Payment.paid_at.label("at"),
        Payment.method.label("method"),
    ).where(Payment.location_id == loc.id, Payment.paid_at >= lo, Payment.paid_at < hi)
    exp_q = select(
        literal("expense").label("kind"),
        Expense.id.label("id"),
        Expense.created_at.label("at"),
        Expense.method.label("method"),
    ).where(
        Expense.location_id == loc.id,
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    )
    ops = union_all(pay_q, exp_q).subquery("ops")
    conds: list[Any] = []
    if kind is not None:
        conds.append(ops.c.kind == kind)
    if method is not None:
        conds.append(ops.c.method == method)
    total = await session.scalar(select(func.count()).select_from(ops).where(*conds))
    page = (
        await session.execute(
            select(ops.c.kind, ops.c.id, ops.c.at)
            .where(*conds)
            .order_by(ops.c.at.desc(), ops.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    pay_ids = [i for k, i, _ in page if k != "expense"]
    exp_ids = [i for k, i, _ in page if k == "expense"]
    payments = (
        {p.id: p for p in await session.scalars(select(Payment).where(Payment.id.in_(pay_ids)))}
        if pay_ids
        else {}
    )
    expenses = (
        {e.id: e for e in await session.scalars(select(Expense).where(Expense.id.in_(exp_ids)))}
        if exp_ids
        else {}
    )
    refundable = await _refundables(session, list(payments.values()))
    numbers = await _order_numbers(session, {p.work_order_id for p in payments.values()})
    cats: dict[uuid.UUID, NameRef] = {}
    if expenses:
        cats = {
            c.id: NameRef(id=c.id, name=c.name)
            for c in await session.scalars(
                select(ExpenseCategory).where(
                    ExpenseCategory.id.in_({e.category_id for e in expenses.values()})
                )
            )
        }
    users = await _users(
        session,
        {p.accepted_by for p in payments.values()} | {e.created_by for e in expenses.values()},
    )
    tz = _tz(loc)
    items: list[CashOperation] = []
    for k, i, at in page:
        if k == "expense":
            e = expenses[i]
            items.append(
                CashOperation(
                    kind="expense",
                    id=e.id,
                    at=at.astimezone(tz),
                    method=e.method,  # type: ignore[arg-type]
                    amount=e.amount,
                    signed_amount=-e.amount,
                    order=None,
                    category=cats[e.category_id],
                    comment=e.description,
                    user=users[e.created_by],
                    is_cancelled=e.cancelled_at is not None,
                    refundable=None,
                )
            )
        else:
            p = payments[i]
            items.append(
                CashOperation(
                    kind=p.payment_type,  # type: ignore[arg-type]
                    id=p.id,
                    at=at.astimezone(tz),
                    method=p.method,  # type: ignore[arg-type]
                    amount=p.amount,
                    signed_amount=p.amount if p.payment_type == "payment" else -p.amount,
                    order=OrderRef(id=p.work_order_id, number=numbers[p.work_order_id]),
                    category=None,
                    comment=p.comment,
                    user=users[p.accepted_by],
                    is_cancelled=False,
                    refundable=refundable.get(p.id) if p.payment_type == "payment" else None,
                )
            )
    return CashOperationPage(items=items, total=int(total or 0))
