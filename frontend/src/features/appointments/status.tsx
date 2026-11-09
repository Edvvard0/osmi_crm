import clsx from "clsx";

import { APPOINTMENT_STATUS_LABELS, type Appointment, type AppointmentStatus } from "@/shared/api/types";

interface StatusStyle {
  /** Цветная полоска слева. */
  stripe: string;
  /** Символ-подсказка: статус различим не только цветом. */
  glyph: string;
  /** Зачёркнутый приглушённый вид для «не приехал» и «отменена». */
  struck: boolean;
}

export const STATUS_STYLE: Record<AppointmentStatus, StatusStyle> = {
  scheduled: { stripe: "border-l-warning", glyph: "○", struck: false },
  confirmed: { stripe: "border-l-accent", glyph: "●", struck: false },
  arrived: { stripe: "border-l-success", glyph: "✓", struck: false },
  no_show: { stripe: "border-l-danger", glyph: "✕", struck: true },
  cancelled: { stripe: "border-l-muted", glyph: "–", struck: true },
};

export function statusBoxClass(s: AppointmentStatus): string {
  const st = STATUS_STYLE[s];
  return clsx("border-l-4 bg-surface", st.stripe, st.struck && "opacity-60");
}

export const struckClass = (s: AppointmentStatus) => (STATUS_STYLE[s].struck ? "line-through" : "");

export function StatusMark({ status }: { status: AppointmentStatus }) {
  return (
    <>
      <span aria-hidden="true">{STATUS_STYLE[status].glyph}</span>
      <span className="sr-only">{APPOINTMENT_STATUS_LABELS[status]}</span>
    </>
  );
}

/** Госномер или марка/модель: что показать на карточке как «имя авто». */
export function vehicleTitle(a: Appointment): string {
  return a.vehicle.plate_number || `${a.vehicle.make} ${a.vehicle.model}`.trim();
}
