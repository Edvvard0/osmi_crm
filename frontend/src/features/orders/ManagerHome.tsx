import { Link } from "react-router-dom";

import { useAppointments, useChangeStatus } from "@/features/appointments/api";
import { hhmm, minuteOfDay, todayIn } from "@/features/appointments/time";
import { useActiveLocation } from "@/features/locations/api";
import { APPOINTMENT_STATUS_LABELS, type Appointment } from "@/shared/api/types";
import { Badge, Button, LinkButton } from "@/shared/ui/ui";

import { useOrderSummary } from "./api";
import { LoadError, Skeleton } from "./ui";

const COUNTERS: { key: "in_progress" | "awaiting_parts" | "ready" | "overdue"; label: string; to: string }[] = [
  { key: "in_progress", label: "В работе", to: "/orders?status=in_progress" },
  { key: "awaiting_parts", label: "Ждут запчасти", to: "/orders?status=awaiting_parts" },
  { key: "ready", label: "Готовы к выдаче", to: "/orders?status=ready" },
  { key: "overdue", label: "Просрочены", to: "/orders?overdue=true" },
];

/** MG-01: счётчики заказов и лента записей на сегодня (блоки модуля 10 здесь не отображаются). */
export function ManagerHome() {
  const { value, current } = useActiveLocation();
  const locationId = value === "all" ? "" : value;
  const summary = useOrderSummary(locationId, value !== "");
  const tz = current?.timezone ?? "Europe/Moscow";
  const today = todayIn(tz, Date.now());
  const apts = useAppointments({ locationId, dateFrom: today, dateTo: today });
  const change = useChangeStatus();

  return (
    <section className="mt-6 space-y-5" aria-label="Сегодня">
      <div>
        <h2 className="mb-2 text-base font-semibold">Заказ-наряды</h2>
        {summary.isLoading ? (
          <Skeleton lines={1} />
        ) : summary.error ? (
          <LoadError error={summary.error} onRetry={() => void summary.refetch()} />
        ) : (
          <ul className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            {COUNTERS.map((c) => {
              const n = summary.data?.[c.key] ?? 0;
              return (
                <li key={c.key}>
                  <Link to={c.to} className="block rounded-lg border border-border bg-surface p-3 hover:bg-bg">
                    <span className={n > 0 && c.key === "overdue" ? "text-2xl font-semibold text-danger" : "text-2xl font-semibold"}>{n}</span>
                    <span className="block text-sm text-muted">{c.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Записи на сегодня</h2>
          <LinkButton variant="secondary" to="/orders/new">Новый заказ</LinkButton>
        </div>
        {!locationId ? (
          <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Выберите точку в шапке, чтобы увидеть записи на сегодня.</p>
        ) : apts.isLoading ? (
          <Skeleton lines={3} />
        ) : apts.error ? (
          <LoadError error={apts.error} onRetry={() => void apts.refetch()} />
        ) : !apts.data?.length ? (
          <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">На сегодня записей нет</p>
        ) : (
          <ul className="space-y-2">
            {[...apts.data]
              .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at))
              .map((a) => (
                <AppointmentLine key={a.id} a={a} tz={tz} busy={change.isPending} onArrived={() => change.mutate({ id: a.id, status: "arrived" })} />
              ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function AppointmentLine({ a, tz, busy, onArrived }: { a: Appointment; tz: string; busy: boolean; onArrived: () => void }) {
  const start = Date.parse(a.start_at);
  const open = a.status === "scheduled" || a.status === "confirmed" || a.status === "arrived";
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3 text-sm">
      <div className="min-w-0">
        <p className="font-medium">
          {hhmm(minuteOfDay(start, tz))} · {a.client.full_name}
        </p>
        <p className="break-words text-muted">
          {a.vehicle.plate_number || `${a.vehicle.make} ${a.vehicle.model}`}
          {a.services.length > 0 && ` · ${a.services.map((s) => s.name).join(", ")}`}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{APPOINTMENT_STATUS_LABELS[a.status]}</Badge>
        {a.work_order_id ? (
          <LinkButton variant="secondary" to={`/orders/${encodeURIComponent(a.work_order_id)}`}>Заказ {a.work_order_number ?? ""}</LinkButton>
        ) : (
          open && (
            <>
              {a.status !== "arrived" && (
                <Button variant="secondary" loading={busy} aria-label={`Приехал: ${a.client.full_name}`} onClick={onArrived}>Приехал</Button>
              )}
              <LinkButton to={`/orders/new?appointment_id=${encodeURIComponent(a.id)}`}>Создать заказ</LinkButton>
            </>
          )
        )}
      </div>
    </li>
  );
}

export function TodayPage() {
  return (
    <div>
      <h1 className="text-xl font-semibold">Сегодня</h1>
      <ManagerHome />
    </div>
  );
}
