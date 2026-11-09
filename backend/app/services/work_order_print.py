"""Печатные формы заказ-наряда (PDF, fpdf2): заказ-наряд и акт выполненных работ.

Данные выводятся только как текст ячеек (разметка fpdf2 выключена), поэтому пользовательские
строки не могут повлиять на структуру документа. Шрифт с кириллицей берётся из системы.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fpdf import FPDF
from fpdf.enums import Align
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Location, User
from app.schemas.work_order import WorkOrderCommentRead, WorkOrderRead
from app.services import work_orders as svc

Kind = Literal["work-order", "act"]

_FONT_DIRS = (
    Path(__file__).resolve().parents[1] / "assets" / "fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("C:/Windows/Fonts"),
)
_FONT_FILES = (("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"), ("arial.ttf", "arialbd.ttf"))
_FONT = "CrmFont"

STATUS_RU = {
    "new": "Новый",
    "diagnostics": "Диагностика",
    "awaiting_approval": "Согласование",
    "in_progress": "В работе",
    "awaiting_parts": "Ожидание запчастей",
    "quality_check": "Проверка качества",
    "ready": "Готов к выдаче",
    "closed": "Закрыт",
    "cancelled": "Отменён",
}


def _find_fonts() -> tuple[Path, Path]:
    for regular, bold in _FONT_FILES:
        for folder in _FONT_DIRS:
            if (folder / regular).is_file() and (folder / bold).is_file():
                return folder / regular, folder / bold
    raise AppError(500, "internal_error")  # шрифт с кириллицей не установлен


def _money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _qty(value: Decimal, places: int) -> str:
    text = f"{value:.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value is not None else "—"


class _Doc(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4")
        regular, bold = _find_fonts()
        self.add_font(_FONT, "", str(regular))
        self.add_font(_FONT, "B", str(bold))
        self.set_auto_page_break(True, margin=15)
        self.set_margins(12, 12, 12)
        self.add_page()

    def title_line(self, text: str, size: int = 14) -> None:
        self.set_font(_FONT, "B", size)
        self.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")

    def line_text(self, text: str, bold: bool = False, size: int = 10) -> None:
        self.set_font(_FONT, "B" if bold else "", size)
        self.multi_cell(0, 5.5, text, new_x="LMARGIN", new_y="NEXT")

    def block(self, label: str, value: str | None) -> None:
        if value:
            self.line_text(label, bold=True)
            self.line_text(value)
            self.ln(1)

    def grid(
        self, widths: tuple[int, ...], header: tuple[str, ...], rows: list[tuple[str, ...]]
    ) -> None:
        self.set_font(_FONT, "B", 9)
        aligns = tuple(Align.L if i == 0 else Align.R for i in range(len(header)))
        with self.table(
            col_widths=widths,
            text_align=aligns,
            line_height=5,
            padding=1,
            first_row_as_headings=True,
        ) as table:
            head = table.row()
            for h in header:
                head.cell(h)
            self.set_font(_FONT, "", 9)
            for r in rows:
                row = table.row()
                for c in r:
                    row.cell(c)
        self.ln(2)


def _header(doc: _Doc, loc: Location, title: str, order: WorkOrderRead) -> None:
    doc.title_line(loc.name, 12)
    doc.line_text(loc.address or "", size=9)
    doc.ln(2)
    doc.title_line(f"{title} № {order.number}")
    doc.line_text(f"Дата: {_dt(order.created_at)}    Статус: {STATUS_RU[order.status]}")
    doc.ln(2)


def _client_block(doc: _Doc, order: WorkOrderRead, with_complaint: bool) -> None:
    doc.line_text(f"Клиент: {order.client.full_name}, {order.client.phone}")
    v = order.vehicle
    car = " ".join(x for x in (v.make, v.model) if x)
    extra = ", ".join(
        x
        for x in (
            f"госномер {v.plate_number}" if v.plate_number else "",
            f"VIN {v.vin}" if v.vin else "",
            f"{v.year} г." if v.year else "",
        )
        if x
    )
    doc.line_text(f"Автомобиль: {car}" + (f", {extra}" if extra else ""))
    if order.mileage_in is not None:
        doc.line_text(f"Пробег при приёме: {order.mileage_in} км")
    doc.line_text(f"Менеджер: {order.manager.full_name}")
    if with_complaint:
        doc.ln(1)
        doc.block("Жалоба клиента:", order.complaint)
        doc.block("Состояние при приёме:", order.intake_notes)
    doc.ln(1)


def _totals(
    doc: _Doc,
    works: Decimal,
    parts: Decimal,
    discount_percent: Decimal,
    discount: Decimal,
    total: Decimal,
) -> None:
    doc.set_font(_FONT, "", 10)
    doc.line_text(f"Работы: {_money(works)}")
    doc.line_text(f"Запчасти и материалы: {_money(parts)}")
    if discount_percent > 0 or discount > 0:
        doc.line_text(f"Скидка {_qty(discount_percent, 2)}%: −{_money(discount)}")
    doc.line_text(f"Итого к оплате: {_money(total)}", bold=True, size=11)
    doc.ln(2)


def _signatures(doc: _Doc) -> None:
    doc.ln(8)
    doc.line_text("Исполнитель: ______________________        Заказчик: ______________________")


def build_pdf(
    kind: Kind,
    order: WorkOrderRead,
    loc: Location,
    comments: list[WorkOrderCommentRead],
) -> bytes:
    act = kind == "act"
    doc = _Doc()
    _header(doc, loc, "Акт выполненных работ к заказ-наряду" if act else "Заказ-наряд", order)
    _client_block(doc, order, with_complaint=not act)

    items = [i for i in order.items if (i.status == "done" if act else i.status != "cancelled")]
    if items:
        doc.title_line("Работы", 11)
        doc.grid(
            (82, 20, 28, 20, 36),
            ("Наименование", "Кол-во", "Цена", "Скидка", "Сумма"),
            [
                (
                    i.name,
                    _qty(i.quantity, 2),
                    _money(i.unit_price),
                    f"{_qty(i.discount_percent, 2)}%",
                    _money(i.total),
                )
                for i in items
            ],
        )
    parts = list(order.parts)
    if parts:
        doc.title_line("Запчасти и материалы", 11)
        doc.grid(
            (82, 20, 28, 20, 36),
            ("Наименование", "Кол-во", "Цена", "", "Сумма"),
            [
                (p.name, _qty(p.quantity, 3), _money(p.unit_price), "", _money(p.total))
                for p in parts
            ],
        )

    if act:
        works = sum((i.total for i in items), Decimal("0.00"))
        parts_sum = sum((p.total for p in parts), Decimal("0.00"))
        discount = svc.q2((works + parts_sum) * order.discount_percent / 100)
        total = works + parts_sum - discount
        _totals(doc, works, parts_sum, order.discount_percent, discount, total)
    else:
        _totals(
            doc,
            order.works_total,
            order.parts_total,
            order.discount_percent,
            order.discount_total,
            order.total,
        )
        if order.planned_ready_at is not None:
            doc.line_text(f"Срок готовности: {_dt(order.planned_ready_at)}")
        visible = [c for c in comments if not c.is_internal]
        if visible:
            doc.ln(1)
            doc.title_line("Примечания", 11)
            for c in visible:
                doc.line_text(f"{_dt(c.created_at)} {c.author.full_name}: {c.text}", size=9)
    _signatures(doc)
    return bytes(doc.output())


async def render(
    session: AsyncSession,
    actor: User,
    allowed: list[uuid.UUID],
    order_id: uuid.UUID,
    kind: Kind,
) -> tuple[bytes, str]:
    order = await svc._get_order(session, allowed, order_id)
    if kind == "act" and order.status not in ("ready", "closed"):
        raise AppError(409, "invalid_state")
    read = await svc._detail(session, order)
    loc = await session.get(Location, order.location_id)
    if loc is None:  # pragma: no cover - FK
        raise AppError(404, "not_found")
    comments = [] if kind == "act" else await svc.list_comments(session, allowed, order_id, False)
    suffix = "act" if kind == "act" else "order"
    return build_pdf(kind, read, loc, comments), f"{order.number}-{suffix}.pdf"
