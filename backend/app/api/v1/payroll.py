import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import Client, Director, SessionDep, require_role
from app.models import Role, User
from app.schemas.payroll import (
    ExportFormat,
    MyEarnings,
    PayrollAdjustmentCreate,
    PayrollAdjustmentRead,
    PayrollDetail,
    PayrollSchemeCreate,
    PayrollSchemePatch,
    PayrollSchemeRead,
    PayrollSheet,
)
from app.services import earnings, payroll, report_export
from app.services.report_common import parse_month

router = APIRouter(tags=["payroll"])

Month = Annotated[str | None, Query(max_length=7)]
Mechanic = Annotated[User, Depends(require_role(Role.mechanic))]


@router.get("/payroll", response_model=PayrollSheet)
async def get_sheet(
    _: Director,
    session: SessionDep,
    month: Month = None,
    location_id: uuid.UUID | None = None,
) -> PayrollSheet:
    return await payroll.get_sheet(session, month, location_id)


@router.get("/payroll/export")
async def export_sheet(
    actor: Director,
    session: SessionDep,
    client: Client,
    month: Month = None,
    location_id: uuid.UUID | None = None,
    format: ExportFormat = "xlsx",
) -> Response:
    report_export.check_export_rate(actor)
    sheet = await payroll.get_sheet(session, month, location_id)
    file = await report_export.export_payroll(
        session, actor, sheet, parse_month(month), format, client
    )
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/payroll/schemes", response_model=list[PayrollSchemeRead])
async def list_schemes(
    _: Director, session: SessionDep, user_id: uuid.UUID | None = None
) -> list[PayrollSchemeRead]:
    return await payroll.list_schemes(session, user_id)


@router.post("/payroll/schemes", response_model=PayrollSchemeRead, status_code=201)
async def create_scheme(
    data: PayrollSchemeCreate, actor: Director, session: SessionDep, client: Client
) -> PayrollSchemeRead:
    return await payroll.create_scheme(session, actor, data, client)


@router.patch("/payroll/schemes/{scheme_id}", response_model=PayrollSchemeRead)
async def patch_scheme(
    scheme_id: uuid.UUID,
    data: PayrollSchemePatch,
    actor: Director,
    session: SessionDep,
    client: Client,
) -> PayrollSchemeRead:
    return await payroll.patch_scheme(session, actor, scheme_id, data, client)


@router.delete("/payroll/schemes/{scheme_id}", status_code=204)
async def delete_scheme(
    scheme_id: uuid.UUID, actor: Director, session: SessionDep, client: Client
) -> Response:
    await payroll.delete_scheme(session, actor, scheme_id, client)
    return Response(status_code=204)


@router.get("/payroll/adjustments", response_model=list[PayrollAdjustmentRead])
async def list_adjustments(
    _: Director,
    session: SessionDep,
    user_id: uuid.UUID | None = None,
    month: Month = None,
) -> list[PayrollAdjustmentRead]:
    return await payroll.list_adjustments(session, user_id, month)


@router.post("/payroll/adjustments", response_model=PayrollAdjustmentRead, status_code=201)
async def create_adjustment(
    data: PayrollAdjustmentCreate, actor: Director, session: SessionDep, client: Client
) -> PayrollAdjustmentRead:
    return await payroll.create_adjustment(session, actor, data, client)


@router.get("/payroll/{user_id}", response_model=PayrollDetail)
async def get_detail(
    user_id: uuid.UUID, _: Director, session: SessionDep, month: Month = None
) -> PayrollDetail:
    return await payroll.get_detail(session, user_id, month)


@router.get("/me/earnings", response_model=MyEarnings)
async def my_earnings(actor: Mechanic, session: SessionDep, month: Month = None) -> MyEarnings:
    return await earnings.my_earnings(session, actor, month)
