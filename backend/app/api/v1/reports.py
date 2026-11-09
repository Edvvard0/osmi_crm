import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.api.deps import AllowedLocations, Client, Director, SessionDep, Staff
from app.schemas.payroll import ExportFormat
from app.schemas.reports import Dashboard, DashboardToday, LocationSummary, Report
from app.services import report_export, report_tables, reports_dashboard

router = APIRouter(tags=["reports"])

Department = Annotated[Literal["service", "detailing"] | None, Query()]
GroupBy = Annotated[str | None, Query(max_length=20)]


@router.get("/reports/dashboard", response_model=Dashboard)
async def get_dashboard(
    actor: Director,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Dashboard:
    return await reports_dashboard.dashboard(
        session, actor, allowed, location_id, date_from, date_to
    )


@router.get("/reports/location-summary", response_model=LocationSummary)
async def get_location_summary(
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    period: Annotated[Literal["day", "week", "month", "custom"], Query()] = "day",
    date_from: date | None = None,
    date_to: date | None = None,
) -> LocationSummary:
    return await reports_dashboard.location_summary(
        session, actor, allowed, location_id, period, date_from, date_to
    )


@router.get("/dashboard/today", response_model=DashboardToday)
async def get_dashboard_today(
    actor: Staff,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
) -> DashboardToday:
    return await reports_dashboard.dashboard_today(session, actor, allowed, location_id)


@router.get("/reports/{report_id}", response_model=Report)
async def get_report(
    report_id: str,
    actor: Director,
    session: SessionDep,
    allowed: AllowedLocations,
    location_id: uuid.UUID | None = None,
    department: Department = None,
    group_by: GroupBy = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Report:
    return await report_tables.build_report(
        session,
        actor,
        allowed,
        report_id,
        location_id=location_id,
        department=department,
        group_by=group_by,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/reports/{report_id}/export")
async def export_report(
    report_id: str,
    actor: Director,
    session: SessionDep,
    allowed: AllowedLocations,
    client: Client,
    format: ExportFormat = "xlsx",
    location_id: uuid.UUID | None = None,
    department: Department = None,
    group_by: GroupBy = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    report_tables.check_report_id(report_id)
    report_export.check_export_rate(actor)
    report = await report_tables.build_report(
        session,
        actor,
        allowed,
        report_id,
        location_id=location_id,
        department=department,
        group_by=group_by,
        date_from=date_from,
        date_to=date_to,
    )
    file = await report_export.export_report(session, actor, report, format, client)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file.filename}"',
            "Cache-Control": "no-store",
        },
    )
