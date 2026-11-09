import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { useActiveLocation } from "@/features/locations/api";
import { Skeleton } from "@/features/orders/ui";
import { formatHours, formatMoney } from "@/shared/lib/money";
import { Button } from "@/shared/ui/ui";

import { ActivityPanel } from "./ActivityPanel";
import { useMyEarnings } from "./api";
import { EmptyNote, QueryError } from "./filters";
import { enc, formatDate, formatDateLong, formatDuration, formatMonth, formatSigned, formatTime, plural, shiftMonth, sign, useToday } from "./lib";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/** M-07: заработок механика за месяц. Цен работ и ставок нет — только то, что вернул сервер. */
export function EarningsPage() {
  const me = useMe();
  const today = useToday();
  const { current } = useActiveLocation();
  const tz = current?.timezone ?? "Europe/Moscow";
  const currentMonth = today.slice(0, 7);
  const [month, setMonth] = useState<string | null>(null);
  const m = month ?? currentMonth;
  const q = useMyEarnings(m);
  const e = q.data && q.data.month === m ? q.data : null;
  const next = shiftMonth(m, 1);
  const adj = e ? sign(e.adjustments_total) : 0;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Заработок</h1>
        <div role="group" aria-label="Месяц" className="flex items-center gap-1">
          <Button variant="secondary" aria-label="Предыдущий месяц" onClick={() => setMonth(shiftMonth(m, -1))}><ChevronLeft size={18} aria-hidden="true" /></Button>
          <span aria-live="polite" className="min-w-36 px-2 text-center text-sm font-medium capitalize">{formatMonth(m)}</span>
          <Button variant="secondary" aria-label="Следующий месяц" disabled={next > currentMonth} onClick={() => setMonth(next)}><ChevronRight size={18} aria-hidden="true" /></Button>
        </div>
      </div>

      {q.error && !e && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
      {!e && !q.error && <Skeleton lines={5} />}

      {e && (
        <>
          {q.error && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
          <section aria-label="Итого за месяц" className="rounded-lg border border-border bg-surface p-4">
            <p className="text-sm text-muted">Итого за месяц</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">{formatMoney(e.total)}</p>
            <p className="mt-2 text-sm text-muted">
              Начислено {formatMoney(e.accrued)}
              {adj !== 0 && <> · премии и удержания {formatSigned(e.adjustments_total)}</>}
            </p>
          </section>

          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Stat label="Выполнено работ" value={String(e.items_done)} />
            <Stat label="Нормочасы" value={formatHours(e.norm_hours)} />
            <Stat label="Фактические часы" value={formatHours(e.actual_hours)} />
          </dl>

          {e.awaiting_close.items_count > 0 && (
            <p className="rounded-lg border border-dashed border-border p-3 text-sm text-muted">
              Ожидают закрытия заказа: {e.awaiting_close.items_count} {plural(e.awaiting_close.items_count, "работа", "работы", "работ")} ({formatHours(e.awaiting_close.norm_hours)}). В заработок войдут после закрытия заказа.
            </p>
          )}

          {e.adjustments.length > 0 && (
            <section aria-label="Премии и удержания">
              <h2 className="mb-2 text-base font-semibold">Премии и удержания</h2>
              <ul className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
                {e.adjustments.map((a, i) => (
                  <li key={`${a.created_at}-${i}`} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2">
                    <div className="min-w-0">
                      <p className="break-words">{a.reason}</p>
                      <p className="text-xs text-muted">{formatDate(a.created_at.slice(0, 10))}</p>
                    </div>
                    <span className={clsx("whitespace-nowrap tabular-nums", sign(a.amount) > 0 && "text-success", sign(a.amount) < 0 && "text-danger")}>
                      {formatSigned(a.amount)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-label="Выполненные работы">
            <h2 className="mb-2 text-base font-semibold">Выполненные работы</h2>
            {e.days.length === 0 ? (
              <EmptyNote>В этом месяце завершённых работ пока нет</EmptyNote>
            ) : (
              <div className="space-y-3">
                {e.days.map((d) => (
                  <div key={d.date}>
                    <h3 className="mb-1 text-sm font-medium text-muted">{formatDateLong(d.date)}</h3>
                    <ul className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
                      {d.items.map((it) => (
                        <li key={it.item_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                          <div className="min-w-0">
                            <p className="break-words font-medium">{it.name}</p>
                            <p className="break-words text-muted">
                              <Link to={`/orders/${enc(it.order.id)}`} className="underline underline-offset-2">Заказ {it.order.number}</Link>
                              {it.plate_number ? ` · ${it.plate_number}` : ""}
                            </p>
                          </div>
                          <p className="whitespace-nowrap text-muted tabular-nums">
                            {formatHours(it.norm_hours_total)} норма · {formatDuration(it.actual_minutes)} · {formatTime(it.finished_at, tz)}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <section aria-label="Мои рабочие дни">
        <h2 className="mb-2 text-base font-semibold">Мои рабочие дни</h2>
        <ActivityPanel userId={me.id} defaultRange="3m" />
      </section>
    </div>
  );
}
