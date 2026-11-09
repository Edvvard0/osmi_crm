"""Единая точка входа склада (api-contract-m8.md).

Все изменения остатков идут через `Ledger` в той же транзакции, что и движение:
строки `stock_balances` блокируются `SELECT … FOR UPDATE` в едином порядке (location_id, part_id),
отсутствующие создаются `INSERT … ON CONFLICT DO NOTHING`. Движения только добавляются.
"""

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ids import new_id
from app.models import Location, Part
from app.models.stock import StockBalance, StockMovement
from app.services import events

Key = tuple[uuid.UUID, uuid.UUID]  # (location_id, part_id)

_CENT = Decimal("0.01")
_MILLI = Decimal("0.001")
_MAX_QTY = Decimal("999999999.999")
ZERO = Decimal(0)


def money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def qty3(value: Decimal) -> str:
    return f"{value.quantize(_MILLI):.3f}"


@dataclass(frozen=True)
class IssueResult:
    movement_id: uuid.UUID
    unit_cost: Decimal  # средняя себестоимость на момент выдачи


def _sorted_keys(keys: Iterable[Key]) -> list[Key]:
    return sorted(set(keys), key=lambda k: (str(k[0]), str(k[1])))


class Ledger:
    """Набор заблокированных строк остатков; `post` добавляет движение и меняет остаток."""

    def __init__(
        self,
        session: AsyncSession,
        actor_id: uuid.UUID,
        balances: dict[Key, StockBalance],
    ) -> None:
        self.session = session
        self.actor_id = actor_id
        self.balances = balances

    @classmethod
    async def open(
        cls, session: AsyncSession, actor_id: uuid.UUID, keys: Iterable[Key]
    ) -> "Ledger":
        ordered = _sorted_keys(keys)
        balances: dict[Key, StockBalance] = {}
        if ordered:
            await session.execute(
                pg_insert(StockBalance)
                .values(
                    [
                        {
                            "location_id": loc,
                            "part_id": part,
                            "quantity": ZERO,
                            "avg_cost": ZERO,
                            "min_quantity": ZERO,
                        }
                        for loc, part in ordered
                    ]
                )
                .on_conflict_do_nothing()
            )
            rows = await session.scalars(
                select(StockBalance)
                .where(tuple_(StockBalance.location_id, StockBalance.part_id).in_(ordered))
                .order_by(StockBalance.location_id, StockBalance.part_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            balances = {(b.location_id, b.part_id): b for b in rows}
        return cls(session, actor_id, balances)

    def balance(self, location_id: uuid.UUID, part_id: uuid.UUID) -> StockBalance:
        return self.balances[(location_id, part_id)]

    async def post(
        self,
        *,
        location_id: uuid.UUID,
        part_id: uuid.UUID,
        movement_type: str,
        quantity: Decimal,
        unit_cost: Decimal | None = None,
        work_order_id: uuid.UUID | None = None,
        related_movement_id: uuid.UUID | None = None,
        supplier: str | None = None,
        document_number: str | None = None,
        reason: str | None = None,
    ) -> StockMovement:
        """Движение со знаком `quantity`.

        Положительное пересчитывает avg_cost; отрицательное идёт по текущей avg_cost (или по
        переданной `unit_cost` — для сторно) и avg_cost не меняет.
        """
        bal = self.balance(location_id, part_id)
        old_qty = bal.quantity
        new_qty = old_qty + quantity
        if new_qty < 0:
            raise AppError(
                409,
                "insufficient_stock",
                details={
                    "part_id": str(part_id),
                    "available": qty3(old_qty),
                    "requested": qty3(-quantity),
                },
            )
        if new_qty > _MAX_QTY:
            raise AppError(422, "validation_error", {"items": "quantity_too_large"})

        cost = bal.avg_cost if unit_cost is None else unit_cost
        if quantity > 0:
            bal.avg_cost = money((old_qty * bal.avg_cost + quantity * cost) / new_qty)
        bal.quantity = new_qty
        bal.updated_at = datetime.now(UTC)

        movement = StockMovement(
            id=new_id(),
            location_id=location_id,
            part_id=part_id,
            movement_type=movement_type,
            quantity=quantity,
            unit_cost=cost,
            balance_after=new_qty,
            work_order_id=work_order_id,
            related_movement_id=related_movement_id,
            supplier=supplier,
            document_number=document_number,
            reason=reason,
            created_by=self.actor_id,
            created_at=datetime.now(UTC),
        )
        self.session.add(movement)

        if (
            quantity < 0
            and bal.min_quantity > 0
            and old_qty >= bal.min_quantity
            and new_qty < bal.min_quantity
        ):
            await self._publish_low(bal)
        return movement

    async def _publish_low(self, bal: StockBalance) -> None:
        part = await self.session.get(Part, bal.part_id)
        loc = await self.session.get(Location, bal.location_id)
        payload: dict[str, str | int | None] = {
            "part_id": str(bal.part_id),
            "sku": part.sku if part else None,
            "name": part.name if part else None,
            "quantity": qty3(bal.quantity),
            "min_quantity": qty3(bal.min_quantity),
            "location_name": loc.name if loc else None,
        }
        await events.publish(
            self.session,
            "stock.low",
            payload,
            location_id=bal.location_id,
            actor_id=self.actor_id,
        )


# ---------------- интеграция с заказ-нарядами (модуль 5) и заявками (модуль 6) ----------------


async def issue_for_order(
    session: AsyncSession,
    *,
    order: Any,
    part_id: uuid.UUID | None,
    quantity: Decimal,
    actor_id: uuid.UUID,
) -> IssueResult | None:
    """Выдача запчасти в заказ. Для произвольной позиции (`part_id is None`) — `None`."""
    if part_id is None:
        return None
    ledger = await Ledger.open(session, actor_id, [(order.location_id, part_id)])
    movement = await ledger.post(
        location_id=order.location_id,
        part_id=part_id,
        movement_type="issue_to_order",
        quantity=-quantity,
        work_order_id=order.id,
    )
    await session.flush()
    return IssueResult(movement_id=movement.id, unit_cost=movement.unit_cost)


async def return_for_order(
    session: AsyncSession, *, order: Any, part_row: Any, actor_id: uuid.UUID
) -> None:
    """Возврат на склад по `part_row.stock_movement_id`; повторный вызов — no-op."""
    movement_id = getattr(part_row, "stock_movement_id", None)
    if movement_id is None:
        return
    original = await session.get(StockMovement, movement_id)
    if original is None:
        return
    ledger = await Ledger.open(session, actor_id, [(original.location_id, original.part_id)])
    already = await session.scalar(
        select(StockMovement.id).where(
            StockMovement.related_movement_id == movement_id,
            StockMovement.movement_type == "return_from_order",
        )
    )
    if already is not None:
        return
    await ledger.post(
        location_id=original.location_id,
        part_id=original.part_id,
        movement_type="return_from_order",
        quantity=Decimal(part_row.quantity),
        unit_cost=original.unit_cost,
        work_order_id=order.id,
        related_movement_id=original.id,
    )
    await session.flush()


async def stock_for_parts(
    session: AsyncSession, *, location_id: uuid.UUID, part_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Остатки по запчастям точки одним запросом; отсутствующая строка остатка — 0."""
    ids = set(part_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(StockBalance.part_id, StockBalance.quantity).where(
            StockBalance.location_id == location_id, StockBalance.part_id.in_(ids)
        )
    )
    result = {pid: ZERO.quantize(_MILLI) for pid in ids}
    result.update({pid: qty for pid, qty in rows})
    return result
