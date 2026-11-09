"""Зарплата: ведомость, схемы оплаты, корректировки (модуль 10, только директор)."""

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, User
from app.models.payroll import PayrollAdjustment, PayrollScheme
from app.schemas.audit import UserRef
from app.schemas.payroll import (
    PayrollAdjustmentCreate,
    PayrollAdjustmentRead,
    PayrollDetail,
    PayrollFixedLine,
    PayrollItemLine,
    PayrollOrderRef,
    PayrollRow,
    PayrollSchemeCreate,
    PayrollSchemePatch,
    PayrollSchemeRead,
    PayrollSheet,
    PayrollTotals,
)
from app.schemas.reports import LocationRef
from app.services.audit import ClientInfo, write_audit
from app.services.payroll_calc import UserCalc, calculate_month, describe_scheme
from app.services.report_common import ZERO, money_s, parse_month, q2, today_app

_EXCLUSION_VIOLATION = "23P01"
MAX_FUTURE_DAYS = 366


def month_label(month: date) -> str:
    return f"{month.year:04d}-{month.month:02d}"


# ---------------- чтение ----------------


def _row(calc: UserCalc) -> PayrollRow:
    return PayrollRow(
        user=UserRef(id=calc.user.id, full_name=calc.user.full_name),
        locations=[LocationRef(id=loc.id, name=loc.name) for loc in calc.locations],
        scheme_summary=calc.scheme_summary,
        items_done=calc.items_done,
        norm_hours=money_s(calc.norm_hours),
        base_amount=money_s(calc.base_amount),
        accrued=money_s(calc.accrued),
        adjustments_total=money_s(calc.adjustments_total),
        total=money_s(calc.total),
        items_without_scheme=calc.items_without_scheme,
    )


async def sheet_rows(
    session: AsyncSession, month: date, location_id: uuid.UUID | None
) -> list[UserCalc]:
    if location_id is not None and await session.get(Location, location_id) is None:
        raise AppError(404, "not_found")
    return list((await calculate_month(session, month, location_id=location_id)).values())


def build_sheet(month: date, location_id: uuid.UUID | None, calcs: list[UserCalc]) -> PayrollSheet:
    totals = PayrollTotals(
        items_done=sum(c.items_done for c in calcs),
        norm_hours=money_s(sum((c.norm_hours for c in calcs), ZERO)),
        base_amount=money_s(sum((c.base_amount for c in calcs), ZERO)),
        accrued=money_s(sum((c.accrued for c in calcs), ZERO)),
        adjustments_total=money_s(sum((c.adjustments_total for c in calcs), ZERO)),
        total=money_s(sum((c.total for c in calcs), ZERO)),
    )
    return PayrollSheet(
        month=month_label(month),
        location_id=location_id,
        rows=[_row(c) for c in calcs],
        totals=totals,
    )


async def get_sheet(
    session: AsyncSession, month_value: str | None, location_id: uuid.UUID | None
) -> PayrollSheet:
    month = parse_month(month_value)
    calcs = await sheet_rows(session, month, location_id)
    return build_sheet(month, location_id, calcs)


async def _user_refs(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, UserRef]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return {uid: UserRef(id=uid, full_name=name) for uid, name in rows}


def _scheme_read(
    scheme: PayrollScheme, users: dict[uuid.UUID, UserRef], today: date
) -> PayrollSchemeRead:
    return PayrollSchemeRead(
        id=scheme.id,
        user=users[scheme.user_id],
        scheme_type=scheme.scheme_type,
        percent=None if scheme.percent is None else money_s(scheme.percent),
        norm_hour_rate=None if scheme.norm_hour_rate is None else money_s(scheme.norm_hour_rate),
        fixed_monthly=None if scheme.fixed_monthly is None else money_s(scheme.fixed_monthly),
        department=scheme.department,
        valid_from=scheme.valid_from,
        valid_to=scheme.valid_to,
        is_current=scheme.valid_from <= today
        and (scheme.valid_to is None or scheme.valid_to >= today),
        description=describe_scheme(scheme),
        created_by=users[scheme.created_by],
        created_at=scheme.created_at,
    )


async def schemes_read(
    session: AsyncSession, schemes: list[PayrollScheme]
) -> list[PayrollSchemeRead]:
    users = await _user_refs(
        session, {s.user_id for s in schemes} | {s.created_by for s in schemes}
    )
    today = today_app()
    return [_scheme_read(s, users, today) for s in schemes]


def _adjustment_read(
    adj: PayrollAdjustment, users: dict[uuid.UUID, UserRef]
) -> PayrollAdjustmentRead:
    return PayrollAdjustmentRead(
        id=adj.id,
        user=users[adj.user_id],
        month=month_label(adj.period_month),
        amount=money_s(adj.amount),
        reason=adj.reason,
        created_by=users[adj.created_by],
        created_at=adj.created_at,
    )


async def adjustments_read(
    session: AsyncSession, items: list[PayrollAdjustment]
) -> list[PayrollAdjustmentRead]:
    users = await _user_refs(session, {a.user_id for a in items} | {a.created_by for a in items})
    return [_adjustment_read(a, users) for a in items]


async def get_detail(
    session: AsyncSession, user_id: uuid.UUID, month_value: str | None
) -> PayrollDetail:
    month = parse_month(month_value)
    if await session.get(User, user_id) is None:
        raise AppError(404, "not_found")
    calc = (await calculate_month(session, month, user_id=user_id)).get(user_id)
    if calc is None:
        raise AppError(404, "not_found")
    return PayrollDetail(
        row=_row(calc),
        items=[
            PayrollItemLine(
                item_id=i.item_id,
                order=PayrollOrderRef(id=i.order_id, number=i.order_number),
                closed_at=i.closed_at,
                name=i.name,
                department=i.department,
                quantity=money_s(i.quantity),
                norm_hours_total=money_s(i.norm_hours_total),
                item_net=money_s(i.item_net),
                scheme_id=i.scheme_id,
                amount=money_s(i.amount),
            )
            for i in calc.items
        ],
        fixed=[
            PayrollFixedLine(
                scheme_id=f.scheme_id,
                days=f.days,
                days_in_month=f.days_in_month,
                amount=money_s(f.amount),
            )
            for f in calc.fixed
        ],
        adjustments=await adjustments_read(session, calc.adjustments),
        schemes=await schemes_read(session, calc.schemes),
    )


# ---------------- схемы ----------------


async def list_schemes(session: AsyncSession, user_id: uuid.UUID | None) -> list[PayrollSchemeRead]:
    stmt = select(PayrollScheme).order_by(
        PayrollScheme.valid_from.desc(), PayrollScheme.created_at.desc(), PayrollScheme.id
    )
    if user_id is not None:
        stmt = stmt.where(PayrollScheme.user_id == user_id)
    return await schemes_read(session, list((await session.scalars(stmt)).all()))


def _validate_fields(data: PayrollSchemeCreate) -> None:
    """Обязательные и лишние поля по типу схемы."""
    required = {
        "percent_of_works": {"percent"},
        "per_norm_hour": {"norm_hour_rate"},
        "fixed_plus_percent": {"percent", "fixed_monthly"},
        "fixed": {"fixed_monthly"},
    }[data.scheme_type]
    fields: dict[str, str] = {}
    for key in ("percent", "norm_hour_rate", "fixed_monthly"):
        value = getattr(data, key)
        if key in required and value is None:
            fields[key] = "required"
        elif key not in required and value is not None:
            fields[key] = "not_allowed"
    if data.scheme_type in ("fixed", "fixed_plus_percent") and data.department is not None:
        fields["department"] = "must_be_null"
    if fields:
        raise AppError(422, "validation_error", fields)


def _is_overlap(exc: IntegrityError) -> bool:
    pgcode = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return str(pgcode) == _EXCLUSION_VIOLATION


def _scheme_snapshot(scheme: PayrollScheme) -> dict[str, str | None]:
    return {
        "user_id": str(scheme.user_id),
        "scheme_type": scheme.scheme_type,
        "percent": None if scheme.percent is None else money_s(scheme.percent),
        "norm_hour_rate": None if scheme.norm_hour_rate is None else money_s(scheme.norm_hour_rate),
        "fixed_monthly": None if scheme.fixed_monthly is None else money_s(scheme.fixed_monthly),
        "department": scheme.department,
        "valid_from": scheme.valid_from.isoformat(),
        "valid_to": None if scheme.valid_to is None else scheme.valid_to.isoformat(),
    }


async def create_scheme(
    session: AsyncSession, actor: User, data: PayrollSchemeCreate, client: ClientInfo
) -> PayrollSchemeRead:
    _validate_fields(data)
    if await session.get(User, data.user_id) is None:
        raise AppError(404, "not_found")

    today = today_app()
    # Параллельные создания схем одного сотрудника выстраиваются в очередь.
    await session.execute(select(User.id).where(User.id == data.user_id).with_for_update())
    same_scope = list(
        (
            await session.scalars(
                select(PayrollScheme)
                .where(
                    PayrollScheme.user_id == data.user_id,
                    func.coalesce(PayrollScheme.department, "*") == (data.department or "*"),
                )
                .order_by(PayrollScheme.valid_from)
            )
        ).all()
    )
    has_any = (
        await session.scalar(
            select(func.count())
            .select_from(PayrollScheme)
            .where(PayrollScheme.user_id == data.user_id)
        )
        or 0
    ) > 0
    if has_any and data.valid_from < today.replace(day=1):
        raise AppError(422, "validation_error", {"valid_from": "closed_month"})
    if data.valid_from > today + timedelta(days=MAX_FUTURE_DAYS):
        raise AppError(422, "validation_error", {"valid_from": "too_far"})

    to_close: PayrollScheme | None = None
    for old in same_scope:
        reaches = old.valid_to is None or old.valid_to >= data.valid_from
        if not reaches:
            continue
        if old.valid_to is None and old.valid_from < data.valid_from:
            to_close = old
            continue
        raise AppError(409, "scheme_overlap")

    scheme = PayrollScheme(
        user_id=data.user_id,
        scheme_type=data.scheme_type,
        percent=data.percent,
        norm_hour_rate=data.norm_hour_rate,
        fixed_monthly=data.fixed_monthly,
        department=data.department,
        valid_from=data.valid_from,
        valid_to=None,
        created_by=actor.id,
    )
    try:
        async with session.begin_nested():
            if to_close is not None:
                old_to = to_close.valid_to
                to_close.valid_to = data.valid_from - timedelta(days=1)
                await session.flush()
            session.add(scheme)
            await session.flush()
    except IntegrityError as exc:
        if _is_overlap(exc):
            raise AppError(409, "scheme_overlap") from None
        raise
    await session.refresh(scheme)
    if to_close is not None:
        write_audit(
            session,
            action="update",
            entity_type="payroll_scheme",
            user_id=actor.id,
            entity_id=to_close.id,
            changes={
                "valid_to": {
                    "old": None if old_to is None else old_to.isoformat(),
                    "new": to_close.valid_to.isoformat() if to_close.valid_to else None,
                }
            },
            client=client,
        )
    write_audit(
        session,
        action="create",
        entity_type="payroll_scheme",
        user_id=actor.id,
        entity_id=scheme.id,
        changes={k: {"old": None, "new": v} for k, v in _scheme_snapshot(scheme).items()},
        client=client,
    )
    await session.commit()
    return (await schemes_read(session, [scheme]))[0]


async def _get_scheme(session: AsyncSession, scheme_id: uuid.UUID) -> PayrollScheme:
    scheme = await session.get(PayrollScheme, scheme_id, with_for_update=True)
    if scheme is None:
        raise AppError(404, "not_found")
    return scheme


async def patch_scheme(
    session: AsyncSession,
    actor: User,
    scheme_id: uuid.UUID,
    data: PayrollSchemePatch,
    client: ClientInfo,
) -> PayrollSchemeRead:
    scheme = await _get_scheme(session, scheme_id)
    today = today_app()
    if data.valid_to < scheme.valid_from:
        raise AppError(422, "validation_error", {"valid_to": "before_valid_from"})
    if data.valid_to < today.replace(day=1):
        raise AppError(422, "validation_error", {"valid_to": "closed_month"})
    old = scheme.valid_to
    if old != data.valid_to:
        try:
            async with session.begin_nested():
                scheme.valid_to = data.valid_to
                await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            if _is_overlap(exc):
                raise AppError(409, "scheme_overlap") from None
            raise
        write_audit(
            session,
            action="update",
            entity_type="payroll_scheme",
            user_id=actor.id,
            entity_id=scheme.id,
            changes={
                "valid_to": {
                    "old": None if old is None else old.isoformat(),
                    "new": data.valid_to.isoformat(),
                }
            },
            client=client,
        )
    await session.commit()
    await session.refresh(scheme)
    return (await schemes_read(session, [scheme]))[0]


async def delete_scheme(
    session: AsyncSession, actor: User, scheme_id: uuid.UUID, client: ClientInfo
) -> None:
    scheme = await _get_scheme(session, scheme_id)
    if scheme.valid_from <= today_app():
        raise AppError(409, "invalid_state")
    snapshot = _scheme_snapshot(scheme)
    await session.delete(scheme)
    write_audit(
        session,
        action="delete",
        entity_type="payroll_scheme",
        user_id=actor.id,
        entity_id=scheme.id,
        changes={k: {"old": v, "new": None} for k, v in snapshot.items()},
        client=client,
    )
    await session.commit()


# ---------------- корректировки ----------------


async def list_adjustments(
    session: AsyncSession, user_id: uuid.UUID | None, month_value: str | None
) -> list[PayrollAdjustmentRead]:
    stmt = select(PayrollAdjustment).order_by(
        PayrollAdjustment.created_at.desc(), PayrollAdjustment.id
    )
    if user_id is not None:
        stmt = stmt.where(PayrollAdjustment.user_id == user_id)
    if month_value is not None:
        stmt = stmt.where(
            PayrollAdjustment.period_month == parse_month(month_value, allow_future=True)
        )
    return await adjustments_read(session, list((await session.scalars(stmt)).all()))


async def create_adjustment(
    session: AsyncSession, actor: User, data: PayrollAdjustmentCreate, client: ClientInfo
) -> PayrollAdjustmentRead:
    fields: dict[str, str] = {}
    if data.amount == 0:
        fields["amount"] = "zero"
    month: date | None = None
    try:
        month = parse_month(data.month)
    except AppError as exc:
        fields.update(exc.fields or {})
    if fields:
        raise AppError(422, "validation_error", fields)
    assert month is not None
    user = await session.get(User, data.user_id)
    if user is None:
        raise AppError(404, "not_found")
    if not user.is_active:
        raise AppError(422, "validation_error", {"user_id": "inactive"})
    adj = PayrollAdjustment(
        user_id=user.id,
        period_month=month,
        amount=q2(data.amount),
        reason=data.reason,
        created_by=actor.id,
    )
    session.add(adj)
    await session.flush()
    await session.refresh(adj)
    write_audit(
        session,
        action="create",
        entity_type="payroll_adjustment",
        user_id=actor.id,
        entity_id=adj.id,
        changes={
            "user_id": {"old": None, "new": str(user.id)},
            "month": {"old": None, "new": month_label(month)},
            "amount": {"old": None, "new": money_s(adj.amount)},
        },
        client=client,
    )
    await session.commit()
    return (await adjustments_read(session, [adj]))[0]
