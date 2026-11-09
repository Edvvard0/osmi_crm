import clsx from "clsx";
import { Ban, CarFront, CircleCheck, Clock, type LucideIcon, UserX } from "lucide-react";

import { APPOINTMENT_STATUS_LABELS, type Appointment, type AppointmentStatus } from "@/shared/api/types";

interface StatusStyle {
  /** Цветная полоска слева. */
  stripe: string;
  /** Иконка-подсказка: статус различим не только цветом. */
  icon: LucideIcon;
  /** Зачёркнутый приглушённый вид для «не приехал» и «отменена». */
  struck: boolean;
}

export const STATUS_STYLE: Record<AppointmentStatus, StatusStyle> = {
  scheduled: { stripe: "border-l-warning", icon: Clock, struck: false },
  confirmed: { stripe: "border-l-accent", icon: CircleCheck, struck: false },
  arrived: { stripe: "border-l-success", icon: CarFront, struck: false },
  no_show: { stripe: "border-l-danger", icon: UserX, struck: true },
  cancelled: { stripe: "border-l-muted", icon: Ban, struck: true },
};

export function statusBoxClass(s: AppointmentStatus): string {
  const st = STATUS_STYLE[s];
  return clsx("border-l-4 bg-surface", st.stripe, st.struck && "opacity-60");
}

export const struckClass = (s: AppointmentStatus) => (STATUS_STYLE[s].struck ? "line-through" : "");

export function StatusIcon({ status, className }: { status: AppointmentStatus; className?: string }) {
  const Icon = STATUS_STYLE[status].icon;
  return <Icon aria-hidden="true" className={clsx("inline-block size-3.5 shrink-0 align-[-2px]", className)} />;
}

export function StatusMark({ status }: { status: AppointmentStatus }) {
  return (
    <>
      <StatusIcon status={status} />
      <span className="sr-only">{APPOINTMENT_STATUS_LABELS[status]}</span>
    </>
  );
}

/** Госномер или марка/модель: что показать на карточке как «имя авто». */
export function vehicleTitle(a: Appointment): string {
  return a.vehicle.plate_number || `${a.vehicle.make} ${a.vehicle.model}`.trim();
}
