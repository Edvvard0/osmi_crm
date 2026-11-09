import { useState } from "react";
import { Link } from "react-router-dom";

import { maskPhone } from "@/shared/lib/masks";
import { APPOINTMENT_STATUS_LABELS, type Appointment, type AppointmentStatus, DEPARTMENT_LABELS } from "@/shared/api/types";
import { Modal } from "@/shared/ui/modal";
import { Badge, Button, LinkButton } from "@/shared/ui/ui";

import { NEXT_STATUSES, isEditable, useChangeStatus } from "./api";
import { STATUS_STYLE, struckClass, vehicleTitle } from "./status";
import { dateOfMs, formatDay, hhmm, minuteOfDay } from "./time";

interface Props {
  appointment: Appointment;
  tz: string;
  postName: string | null;
  onClose: () => void;
  onEdit: () => void;
}

/** Кнопки перехода статуса: подпись действия, а не названия статуса. */
const ACTION_LABEL: Record<AppointmentStatus, string> = {
  scheduled: "Запланирована",
  confirmed: "Подтвердить",
  arrived: "Клиент приехал",
  no_show: "Не приехал",
  cancelled: "Отменить",
};
/** Необратимые переходы: перед отправкой просим подтверждение. */
const NEEDS_CONFIRM: AppointmentStatus[] = ["no_show", "cancelled"];
const CONFIRM_TEXT: Partial<Record<AppointmentStatus, string>> = {
  no_show: "Отметить, что клиент не приехал? Статус нельзя будет изменить.",
  cancelled: "Отменить запись? Статус нельзя будет изменить.",
};

const TONE: Record<AppointmentStatus, "neutral" | "success" | "warning" | "danger"> = {
  scheduled: "warning",
  confirmed: "neutral",
  arrived: "success",
  no_show: "danger",
  cancelled: "neutral",
};

export function AppointmentDetails({ appointment: a, tz, postName, onClose, onEdit }: Props) {
  const change = useChangeStatus();
  const [confirming, setConfirming] = useState<AppointmentStatus | null>(null);
  const s = Date.parse(a.start_at);
  const e = Date.parse(a.end_at);
  const next = NEXT_STATUSES[a.status];

  function run(status: AppointmentStatus) {
    setConfirming(null);
    change.mutate({ id: a.id, status }, { onSuccess: onClose });
  }

  return (
    <Modal title="Запись" onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={TONE[a.status]}>
            <span aria-hidden="true">{STATUS_STYLE[a.status].glyph}</span> {APPOINTMENT_STATUS_LABELS[a.status]}
          </Badge>
          <span className={struckClass(a.status)}>
            {formatDay(dateOfMs(s, tz))}, {hhmm(minuteOfDay(s, tz))}–{hhmm(minuteOfDay(e, tz))}
          </span>
        </div>

        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2">
          <dt className="text-muted">Клиент</dt>
          <dd className="min-w-0 break-words">
            <Link className="font-medium underline" to={`/clients/${encodeURIComponent(a.client_id)}`}>{a.client.full_name}</Link>{" "}
            <span className="text-muted">{maskPhone(a.client.phone)}</span>
          </dd>
          <dt className="text-muted">Автомобиль</dt>
          <dd className="min-w-0 break-words">
            <Link className="font-medium underline" to={`/vehicles/${encodeURIComponent(a.vehicle_id)}`}>{vehicleTitle(a)}</Link>
            {a.vehicle.plate_number && <span className="text-muted"> {a.vehicle.make} {a.vehicle.model}</span>}
          </dd>
          <dt className="text-muted">Отдел</dt>
          <dd>{DEPARTMENT_LABELS[a.department]}</dd>
          <dt className="text-muted">Пост</dt>
          <dd>{postName ?? "Без поста"}</dd>
          <dt className="text-muted">Услуги</dt>
          <dd className="min-w-0 break-words">{a.services.length ? a.services.map((x) => x.name).join(", ") : "—"}</dd>
          {a.work_order_id && (
            <>
              <dt className="text-muted">Заказ-наряд</dt>
              <dd><Link className="font-medium underline" to={`/orders/${encodeURIComponent(a.work_order_id)}`}>Заказ {a.work_order_number ?? ""}</Link></dd>
            </>
          )}
          <dt className="text-muted">Комментарий</dt>
          <dd className="min-w-0 whitespace-pre-wrap break-words">{a.comment || "—"}</dd>
        </dl>

        {confirming ? (
          <div role="alertdialog" aria-label="Подтверждение" className="space-y-2 rounded border border-border p-3">
            <p>{CONFIRM_TEXT[confirming]}</p>
            <div className="flex gap-2">
              <Button type="button" variant="danger" loading={change.isPending} onClick={() => run(confirming)}>
                Да, {ACTION_LABEL[confirming].toLowerCase()}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setConfirming(null)}>Назад</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {next.map((st) => (
              <Button
                key={st}
                type="button"
                variant={st === "confirmed" || st === "arrived" ? "primary" : "secondary"}
                loading={change.isPending}
                onClick={() => (NEEDS_CONFIRM.includes(st) ? setConfirming(st) : run(st))}
              >
                {ACTION_LABEL[st]}
              </Button>
            ))}
            {!a.work_order_id && (a.status === "scheduled" || a.status === "confirmed" || a.status === "arrived") && (
              <LinkButton to={`/orders/new?appointment_id=${encodeURIComponent(a.id)}`}>Создать заказ</LinkButton>
            )}
            {isEditable(a.status) && <Button type="button" variant="ghost" onClick={onEdit}>Редактировать</Button>}
          </div>
        )}
      </div>
    </Modal>
  );
}
