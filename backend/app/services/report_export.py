"""Экспорт отчётов и ведомости в XLSX и CSV (модуль 10).

XLSX собирается вручную (zip + XML), внешних библиотек не требуется.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ratelimit import RateLimiter
from app.models import User
from app.schemas.payroll import PayrollSheet
from app.schemas.reports import Report
from app.services.audit import ClientInfo, write_audit
from app.services.report_common import month_bounds

MAX_EXPORT_ROWS = 100_000
EXPORT_PER_MINUTE = 10
NUMERIC_KINDS = frozenset({"money", "hours", "count", "percent"})
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_TYPE = "text/csv; charset=utf-8"

export_limiter = RateLimiter()

_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


@dataclass
class Column:
    key: str
    title: str
    kind: str


@dataclass
class Table:
    columns: list[Column]
    rows: list[dict[str, str | None]]
    totals: dict[str, str | None] | None


def check_export_rate(user: User) -> None:
    if not export_limiter.allow(f"export:{user.id}", EXPORT_PER_MINUTE):
        raise AppError(429, "rate_limited")


def safe_text(value: str | None) -> str:
    """Защита от формульных инъекций: префикс `'` для опасных первых символов."""
    if not value:
        return ""
    return "'" + value if value.startswith(FORMULA_START) else value


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


# ---------------- таблицы ----------------


def report_table(report: Report) -> Table:
    return Table(
        [Column(c.key, c.title, c.kind) for c in report.columns], report.rows, report.totals
    )


PAYROLL_COLUMNS = [
    Column("user", "Сотрудник", "text"),
    Column("locations", "Точки", "text"),
    Column("scheme_summary", "Схема оплаты", "text"),
    Column("items_done", "Работ выполнено", "count"),
    Column("norm_hours", "Нормочасы", "hours"),
    Column("base_amount", "База", "money"),
    Column("accrued", "Начислено", "money"),
    Column("adjustments_total", "Корректировки", "money"),
    Column("total", "К выплате", "money"),
    Column("items_without_scheme", "Работ без схемы", "count"),
]


def payroll_table(sheet: PayrollSheet) -> Table:
    rows: list[dict[str, str | None]] = [
        {
            "user": r.user.full_name,
            "locations": ", ".join(loc.name for loc in r.locations),
            "scheme_summary": r.scheme_summary,
            "items_done": str(r.items_done),
            "norm_hours": r.norm_hours,
            "base_amount": r.base_amount,
            "accrued": r.accrued,
            "adjustments_total": r.adjustments_total,
            "total": r.total,
            "items_without_scheme": str(r.items_without_scheme),
        }
        for r in sheet.rows
    ]
    t = sheet.totals
    totals: dict[str, str | None] = {
        "user": "Итого",
        "locations": None,
        "scheme_summary": None,
        "items_done": str(t.items_done),
        "norm_hours": t.norm_hours,
        "base_amount": t.base_amount,
        "accrued": t.accrued,
        "adjustments_total": t.adjustments_total,
        "total": t.total,
        "items_without_scheme": str(sum(r.items_without_scheme for r in sheet.rows)),
    }
    return Table(list(PAYROLL_COLUMNS), rows, totals)


def _all_rows(table: Table) -> list[dict[str, str | None]]:
    if len(table.rows) > MAX_EXPORT_ROWS:
        raise AppError(422, "validation_error", {"export": "too_many_rows"})
    return table.rows + ([table.totals] if table.totals else [])


# ---------------- CSV ----------------


def to_csv(table: Table) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([safe_text(c.title) for c in table.columns])
    for row in _all_rows(table):
        out: list[str] = []
        for c in table.columns:
            value = row.get(c.key)
            if c.kind in NUMERIC_KINDS:
                out.append("" if value is None else value.replace(".", ","))
            else:
                out.append(safe_text(value))
        writer.writerow(out)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


# ---------------- XLSX ----------------

_STYLE = {"text": 0, "header": 1, "money": 2, "hours": 3, "count": 4, "percent": 3}

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)
_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Отчёт" sheetId="1" r:id="rId1"/></sheets></workbook>'
)
_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    "</Relationships>"
)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="5">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _col_letter(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xml_text(value: str) -> str:
    return escape(_XML_BAD.sub("", value))


def _text_cell(ref: str, value: str, style: int = 0) -> str:
    if value == "":
        return ""
    return (
        f'<c r="{ref}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{_xml_text(value)}</t></is></c>'
    )


def _sheet_xml(table: Table) -> str:
    rows = _all_rows(table)
    widths = [min(max(len(c.title), 10), 60) for c in table.columns]
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    parts.append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
    parts.append(
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
    )
    body: list[str] = []
    header = "".join(
        _text_cell(f"{_col_letter(i)}1", safe_text(c.title), _STYLE["header"])
        for i, c in enumerate(table.columns)
    )
    body.append(f'<row r="1">{header}</row>')
    for r_index, row in enumerate(rows, start=2):
        cells: list[str] = []
        for i, c in enumerate(table.columns):
            value = row.get(c.key)
            ref = f"{_col_letter(i)}{r_index}"
            if value is not None:
                widths[i] = min(max(widths[i], len(value) + 2), 60)
            if c.kind in NUMERIC_KINDS:
                number = _to_decimal(value)
                if number is not None:
                    cells.append(f'<c r="{ref}" s="{_STYLE[c.kind]}"><v>{number}</v></c>')
                continue
            cells.append(_text_cell(ref, safe_text(value)))
        body.append(f'<row r="{r_index}">{"".join(cells)}</row>')
    parts.append(
        "<cols>"
        + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)
        )
        + "</cols>"
    )
    parts.append("<sheetData>" + "".join(body) + "</sheetData></worksheet>")
    return "".join(parts)


def to_xlsx(table: Table) -> bytes:
    buf = io.BytesIO()
    files = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/styles.xml": _STYLES,
        "xl/worksheets/sheet1.xml": _sheet_xml(table),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content.encode("utf-8"))
    return buf.getvalue()


# ---------------- публичный API ----------------


@dataclass
class ExportFile:
    content: bytes
    media_type: str
    filename: str


def _render(table: Table, fmt: str, stem: str) -> ExportFile:
    if fmt == "csv":
        return ExportFile(to_csv(table), CSV_TYPE, f"{stem}.csv")
    return ExportFile(to_xlsx(table), XLSX_TYPE, f"{stem}.xlsx")


async def export_report(
    session: AsyncSession,
    actor: User,
    report: Report,
    fmt: str,
    client: ClientInfo,
) -> ExportFile:
    result = _render(
        report_table(report), fmt, f"report-{report.id}-{report.date_from}_{report.date_to}"
    )
    write_audit(
        session,
        action="export",
        entity_type="report",
        user_id=actor.id,
        location_id=report.location_id,
        changes={
            "report_id": report.id,
            "format": fmt,
            "date_from": report.date_from.isoformat(),
            "date_to": report.date_to.isoformat(),
            "location_id": None if report.location_id is None else str(report.location_id),
        },
        client=client,
    )
    await session.commit()
    return result


async def export_payroll(
    session: AsyncSession,
    actor: User,
    sheet: PayrollSheet,
    month: date,
    fmt: str,
    client: ClientInfo,
) -> ExportFile:
    result = _render(payroll_table(sheet), fmt, f"payroll-{sheet.month}")
    first, last = month_bounds(month)
    write_audit(
        session,
        action="export",
        entity_type="payroll",
        user_id=actor.id,
        location_id=sheet.location_id,
        changes={
            "kind": "payroll",
            "format": fmt,
            "date_from": first.isoformat(),
            "date_to": last.isoformat(),
            "location_id": None if sheet.location_id is None else str(sheet.location_id),
        },
        client=client,
    )
    await session.commit()
    return result
