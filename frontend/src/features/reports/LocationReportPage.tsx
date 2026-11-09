import clsx from "clsx";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useActiveLocation } from "@/features/locations/api";
import { Skeleton } from "@/features/orders/ui";
import { formatHours, formatMoney } from "@/shared/lib/money";

import { useLocationSummary } from "./api";
import { BarChart, LineChart } from "./charts";
import { EmptyNote, QueryError } from "./filters";
import { enc, formatDate, formatDateShort, formatPercent, num, sign } from "./lib";
import type { SummaryPeriod } from "./types";

const PERIODS: { value: SummaryPeriod; label: string }[] = [
  { value: "day", label: "День" },
  { value: "week", label: "Неделя" },
  { value: "month", label: "Месяц" },
];

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/** MG-16: сводка точки для менеджера (и директора). Без расходов, себестоимости и зарплат. */
export function LocationReportPage() {
  const { value, isDirector, loading } = useActiveLocation();
  const [period, setPeriod] = useState<SummaryPeriod>("day");
  const needsLocation = !isDirector && !value;
  const q = useLocationSummary({ locationId: value, period, enabled: !loading && !needsLocation });
  const s = q.data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Отчёт точки</h1>
          {s && (
            <p className="mt-1 text-sm text-muted">
              {s.location.name} · {formatDate(s.date_from)}
              {s.date_to !== s.date_from ? ` — ${formatDate(s.date_to)}` : ""}
            </p>
          )}
        </div>
        <div role="group" aria-label="Период" className="inline-flex overflow-hidden rounded border border-border">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              aria-pressed={period === p.value}
              onClick={() => setPeriod(p.value)}
              className={clsx("min-h-10 border-r border-border px-4 text-sm last:border-r-0", period === p.value ? "bg-accent text-accent-fg" : "bg-surface text-fg hover:bg-bg")}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {needsLocation && !loading && <EmptyNote>Нет доступной точки. Обратитесь к директору.</EmptyNote>}
      {q.error && !s && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
      {!s && !q.error && !needsLocation && <Skeleton lines={4} />}

      {s && (
        <>
          {q.error && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile label="Выручка" value={formatMoney(s.revenue)} />
            <Tile label="Закрыто заказов" value={String(s.orders_closed)} />
            <Tile label="Средний чек" value={formatMoney(s.average_check)} />
            <Tile label="Загрузка постов" value={formatPercent(s.post_load)} />
          </dl>

          <section aria-label="Выручка по дням" className="rounded-lg border border-border bg-surface p-4">
            <h2 className="mb-3 text-base font-semibold">Выручка</h2>
            {s.series.length === 0 || s.series.every((p) => sign(p.revenue) === 0) ? (
              <EmptyNote>Нет данных за период</EmptyNote>
            ) : s.series.length === 1 ? (
              <BarChart
                categories={s.series.map((p) => formatDateShort(p.date))}
                series={[{ key: "revenue", title: "Выручка", values: s.series.map((p) => num(p.revenue)) }]}
                format={(v) => formatMoney(v.toFixed(2))}
                label="График выручки"
              />
            ) : (
              <LineChart
                categories={s.series.map((p) => formatDateShort(p.date))}
                series={[{ key: "revenue", title: "Выручка", values: s.series.map((p) => num(p.revenue)) }]}
                format={(v) => formatMoney(v.toFixed(2))}
                label="График выручки"
              />
            )}
          </section>

          <section aria-label="Выработка механиков">
            <h2 className="mb-2 text-base font-semibold">Выработка механиков</h2>
            {s.mechanics.length === 0 ? (
              <EmptyNote>За период нет выполненных работ</EmptyNote>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border bg-surface">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wide text-muted">
                      <th scope="col" className="px-3 py-2 font-medium">Механик</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Работ</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Нормочасы</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Факт, ч</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Эффективность</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Сумма работ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.mechanics.map((m) => (
                      <tr key={m.user.id} className="border-t border-border">
                        <td className="break-words px-3 py-2">
                          <Link to={`/mechanics/${enc(m.user.id)}`} className="underline underline-offset-2">{m.user.full_name}</Link>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{m.items_done}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{formatHours(m.norm_hours)}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{formatHours(m.actual_hours)}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{m.efficiency === null ? "—" : formatPercent(m.efficiency)}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">{formatMoney(m.works_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
