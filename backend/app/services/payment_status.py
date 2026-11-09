"""Статус оплаты заказа: пересчитывается при платеже/возврате и при изменении `total` заказа."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.cash import Payment

_ZERO = Decimal("0.00")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


async def payment_sums(
    session: AsyncSession, order_id: uuid.UUID
) -> tuple[Decimal, Decimal, int, int]:
    """(сумма платежей, сумма возвратов, число платежей, число возвратов)."""
    is_pay = Payment.payment_type == "payment"
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(case((is_pay, Payment.amount), else_=0)), 0),
                func.coalesce(func.sum(case((is_pay, 0), else_=Payment.amount)), 0),
                func.count().filter(is_pay),
                func.count().filter(~is_pay),
            ).where(Payment.work_order_id == order_id)
        )
    ).one()
    return Decimal(row[0]), Decimal(row[1]), int(row[2]), int(row[3])


async def refunded_total(session: AsyncSession, order_id: uuid.UUID) -> Decimal:
    """Сумма всех возвратов по заказу (поле `WorkOrder.refunded_total`)."""
    await session.flush()
    return _q((await payment_sums(session, order_id))[1])


def status_for(total: Decimal, paid: Decimal, refunded: Decimal, pay_count: int) -> str:
    net = paid - refunded
    if pay_count == 0:
        return "paid" if total == 0 else "unpaid"
    if net <= 0:
        return "refunded" if refunded > 0 else "unpaid"
    return "paid" if net >= total else "partial"


async def recalc_payment_status(session: AsyncSession, order: Any) -> None:
    """Обновляет `order.paid_total` (чистая оплата) и `order.payment_status`.

    При `total < net` бросает 409 `total_below_paid`: вызывающий сервис откатывает транзакцию.
    """
    await session.flush()
    paid, refunded, pay_count, _ = await payment_sums(session, order.id)
    net = _q(paid - refunded)
    total = _q(Decimal(order.total))
    if total < net:
        raise AppError(
            409,
            "total_below_paid",
            details={"total": f"{total:.2f}", "paid_total": f"{net:.2f}"},
        )
    order.paid_total = net
    order.payment_status = status_for(total, paid, refunded, pay_count)
