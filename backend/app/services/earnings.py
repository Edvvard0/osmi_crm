"""Заработок механика (M-07): без цен работ, скидок и ставок — только итог и нормочасы."""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.work_order import WorkOrder, WorkOrderItem
from app.schemas.payroll import (
    AwaitingClose,
    EarningsAdjustment,
    EarningsDay,
    EarningsItem,
    MyEarnings,
    PayrollOrderRef,
)
from app.services.payroll import month_label
from app.services.payroll_calc import calculate_month
from app.services.report_common import ZERO, dec, hours_from_minutes, money_s, parse_month, q2


async def my_earnings(session: AsyncSession, actor: User, month_value: str | None) -> MyEarnings:
    month = parse_month(month_value)
    calc = (await calculate_month(session, month, user_id=actor.id)).get(actor.id)

    awaiting_count = 0
    awaiting_hours = ZERO
    row = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(WorkOrderItem.norm_hours * WorkOrderItem.quantity), 0),
            )
            .select_from(WorkOrderItem)
            .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
            .where(
                WorkOrderItem.mechanic_id == actor.id,
                WorkOrderItem.status == "done",
                WorkOrder.status.notin_(("closed", "cancelled")),
            )
        )
    ).one()
    awaiting_count, awaiting_hours = int(row[0]), q2(dec(row[1]))

    days: dict[date, list[EarningsItem]] = {}
    adjustments: list[EarningsAdjustment] = []
    accrued = adj_total = total = norm_hours = ZERO
    items_done = 0
    actual_minutes = 0
    if calc is not None:
        accrued, adj_total, total = calc.accrued, calc.adjustments_total, calc.total
        norm_hours, items_done, actual_minutes = calc.norm_hours, calc.items_done, calc.actual_minutes
        adjustments = [
            EarningsAdjustment(amount=money_s(a.amount), reason=a.reason, created_at=a.created_at)
            for a in sorted(calc.adjustments, key=lambda a: a.created_at, reverse=True)
        ]
        for line in calc.items:
            days.setdefault(line.day, []).append(
                EarningsItem(
                    item_id=line.item_id,
                    order=PayrollOrderRef(id=line.order_id, number=line.order_number),
                    plate_number=line.plate_number,
                    name=line.name,
                    norm_hours_total=money_s(line.norm_hours_total),
                    actual_minutes=line.actual_minutes,
                    finished_at=line.finished_at,
                )
            )
    return MyEarnings(
        month=month_label(month),
        accrued=money_s(accrued),
        adjustments_total=money_s(adj_total),
        total=money_s(total),
        items_done=items_done,
        norm_hours=money_s(norm_hours),
        actual_hours=money_s(hours_from_minutes(actual_minutes)),
        adjustments=adjustments,
        awaiting_close=AwaitingClose(items_count=awaiting_count, norm_hours=money_s(awaiting_hours)),
        days=[EarningsDay(date=d, items=days[d]) for d in sorted(days, reverse=True)],
        server_time=datetime.now(UTC),
    )
