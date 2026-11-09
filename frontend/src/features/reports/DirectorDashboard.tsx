import clsx from "clsx";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useActiveLocation } from "@/features/locations/api";
import { Skeleton, fmtDateTime, useTzOf } from "@/features/orders/ui";
import { Badge, Table, Td, Th } from "@/shared/ui/ui";
import { formatMoney } from "@/shared/lib/money";

import { useDashboard } from "./api";
import { BarChart, LineChart } from "./charts";
import { EmptyNote, PeriodFilter, QueryError, usePeriod } from "./filters";
import { enc, formatDateShort, formatDelta, formatPercent, formatQty, num, sign } from "./lib";
import type { Dashboard, Kpi, ReportId } from "./types";

type KpiKey = keyof Dashboard["kpis"];

const KPI_DEFS: { key: KpiKey; label: string; report: ReportId }[] = [
  { key: "revenue", label: "Выручка", report: "revenue" },
  { key: "cash_received", label: "Поступления в кассу", report: "revenue" },
  { key: "orders_closed", label: "Закрыто заказов", report: "revenue" },
  { key: "average_check", label: "Средний чек", report: "revenue" },
  { key: "post_load", label: "Загрузка постов", report: "mechanics" },
  { key: "detailing_share", label: "Доля детейлинга", report: "services" },
  { key: "conversion", label: "Конверсия записей", report: "clients" },
  { key: "new_clients", label: "Новые клиенты", report: "clients" },
  { key: "repeat_clients", label: "Повторные клиенты", report: "clients" },
];

function kpiValue(k: Kpi, v: string): string {
  if (k.kind === "money") return formatMoney(v);
  if (k.kind === "percent") return formatPercent(v);
  return formatQty(v);
}

function KpiTile({ def, kpi, to }: { def: (typeof KPI_DEFS)[number]; kpi: Kpi; to: string }) {
  const d = formatDelta(kpi.kind, kpi.delta);
  return (
    <li>
      <Link to={to} className="block h-full rounded-lg border border-border bg-surface p-3 hover:bg-bg">
        <span className="block text-sm text-muted">{def.label}</span>
        <span className="mt-1 block break-words text-xl font-semibold">{kpiValue(kpi, kpi.value)}</span>
        <span className="mt-1 flex flex-wrap items-baseline gap-x-2 text-xs">
          <span className={clsx(d.sign > 0 && "text-success", d.sign < 0 && "text-danger", d.sign === 0 && "text-muted")}>
            <span className="sr-only">{d.sign > 0 ? "Рост: " : d.sign < 0 ? "Снижение: " : "Изменение: "}</span>
            {d.text}
          </span>
          <span className="text-muted">было {kpiValue(kpi, kpi.previous)}</span>
        </span>
      </Link>
    </li>
  );
}

const MONEY_AXIS = (v: number) => formatMoney(v.toFixed(2));

function RevenueChart({ series }: { series: Dashboard["revenue_series"] }) {
  const [mode, setMode] = useState<"total" | "dept">("total");
  const categories = series.map((p) => formatDateShort(p.date));
  const chartSeries =
    mode === "total"
      ? [{ key: "total", title: "Выручка", values: series.map((p) => num(p.total)) }]
      : [
          { key: "service_works", title: "Сервис", values: series.map((p) => num(p.by_department.service_works)) },
          { key: "detailing_works", title: "Детейлинг", values: series.map((p) => num(p.by_department.detailing_works)) },
          { key: "parts", title: "Запчасти", values: series.map((p) => num(p.by_department.parts)) },
        ];
  const Chart = series.length <= 1 ? BarChart : LineChart;
  return (
    <section aria-label="Выручка по дням" className="rounded-lg border border-border bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Выручка по дням</h2>
        <div role="group" aria-label="Разбивка" className="inline-flex overflow-hidden rounded border border-border text-sm">
          {(["total", "dept"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={clsx("min-h-9 border-r border-border px-3 last:border-r-0", mode === m ? "bg-accent text-accent-fg" : "bg-surface hover:bg-bg")}
            >
              {m === "total" ? "Итого" : "По отделам"}
            </button>
          ))}
        </div>
      </div>
      {series.length === 0 ? (
        <EmptyNote>Нет данных за период</EmptyNote>
      ) : (
        <Chart categories={categories} series={chartSeries} format={MONEY_AXIS} label={mode === "total" ? "График выручки по дням" : "График выручки по отделам"} />
      )}
    </section>
  );
}

function Attention({ a }: { a: Dashboard["attention"] }) {
  const tzOf = useTzOf();
  const nothing = a.refunds.count === 0 && a.big_discounts.count === 0 && a.overdue_orders.count === 0 && a.low_stock.count === 0;
  return (
    <section aria-label="Внимание" className="rounded-lg border border-border bg-surface p-4">
      <h2 className="mb-3 text-base font-semibold">Внимание</h2>
      {nothing ? (
        <p className="text-sm text-muted">Всё в порядке: возвратов, больших скидок, просрочек и дефицита нет.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium">
              Возвраты <Badge tone={a.refunds.count > 0 ? "warning" : "neutral"}>{a.refunds.count}</Badge>
            </h3>
            <p className="mt-1 text-sm text-muted">{a.refunds.count > 0 ? `На сумму ${formatMoney(a.refunds.total)}` : "За период возвратов не было"}</p>
          </div>
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium">
              Большие скидки <Badge tone={a.big_discounts.count > 0 ? "warning" : "neutral"}>{a.big_discounts.count}</Badge>
            </h3>
            <p className="text-xs text-muted">Скидка от {formatPercent(a.big_discounts.threshold)}</p>
            <ul className="mt-1 space-y-1 text-sm">
              {a.big_discounts.items.map((o) => (
                <li key={o.id} className="flex flex-wrap justify-between gap-2">
                  <Link to={`/orders/${enc(o.id)}`} className="underline underline-offset-2">Заказ {o.number}</Link>
                  <span className="text-muted">{o.location.name} · {formatPercent(o.value)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium">
              Просроченные заказы <Badge tone={a.overdue_orders.count > 0 ? "danger" : "neutral"}>{a.overdue_orders.count}</Badge>
            </h3>
            <ul className="mt-1 space-y-1 text-sm">
              {a.overdue_orders.items.map((o) => (
                <li key={o.id} className="flex flex-wrap justify-between gap-2">
                  <Link to={`/orders/${enc(o.id)}`} className="underline underline-offset-2">Заказ {o.number}</Link>
                  <span className="text-muted">{o.location.name} · срок {fmtDateTime(o.value, tzOf(o.location.id))}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="flex items-center gap-2 text-sm font-medium">
              Заканчиваются запчасти <Badge tone={a.low_stock.count > 0 ? "warning" : "neutral"}>{a.low_stock.count}</Badge>
            </h3>
            <ul className="mt-1 space-y-1 text-sm">
              {a.low_stock.items.map((s) => (
                <li key={`${s.location.id}-${s.part.id}`} className="flex flex-wrap justify-between gap-2">
                  <span className="min-w-0 break-words">
                    <Link to={`/stock/${enc(s.part.id)}?location_id=${enc(s.location.id)}`} className="underline underline-offset-2">{s.part.name}</Link>{" "}
                    <span className="text-muted">({s.part.sku})</span>
                  </span>
                  <span className="text-muted">{s.location.name} · {formatQty(s.quantity)} из {formatQty(s.min_quantity)}</span>
                </li>
              ))}
            </ul>
            {a.low_stock.count > 0 && (
              <Link to="/stock" className="mt-1 inline-block text-xs text-muted underline underline-offset-2">Открыть склад</Link>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** D-01: рабочий стол директора. Точка берётся из переключателя в шапке («Все точки» или одна). */
export function DirectorDashboard() {
  const { value, current } = useActiveLocation();
  const period = usePeriod("month");
  const q = useDashboard({ locationId: value, dateFrom: period.from, dateTo: period.to });
  const d = q.data;
  const empty = !!d && sign(d.kpis.revenue.value) === 0 && sign(d.kpis.orders_closed.value) === 0 && d.revenue_series.every((p) => sign(p.total) === 0);
  const reportLink = (report: ReportId) => `/reports?report=${report}&date_from=${period.from}&date_to=${period.to}`;

  return (
    <div className="mt-4 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PeriodFilter period={period} idPrefix="dash" />
        <p className="text-sm text-muted">{value === "all" ? "Все точки" : (current?.name ?? "")}</p>
      </div>

      {q.isLoading && (
        <div role="status" aria-label="Загрузка" className="grid animate-pulse grid-cols-2 gap-3 lg:grid-cols-3">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="h-24 rounded-lg bg-border/50" />
          ))}
        </div>
      )}
      {q.error && !d && <QueryError error={q.error} onRetry={() => void q.refetch()} />}

      {d && (
        <>
          {q.error && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
          {empty && <EmptyNote>Нет данных за период</EmptyNote>}
          <ul className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {KPI_DEFS.map((def) => (
              <KpiTile key={def.key} def={def} kpi={d.kpis[def.key]} to={reportLink(def.report)} />
            ))}
          </ul>

          <RevenueChart series={d.revenue_series} />

          <section aria-label="Сравнение точек">
            <h2 className="mb-2 text-base font-semibold">Точки</h2>
            {d.locations.length === 0 ? (
              <EmptyNote>Нет данных за период</EmptyNote>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Точка</Th>
                    <Th>Выручка</Th>
                    <Th>Заказов</Th>
                    <Th>Средний чек</Th>
                    <Th>Загрузка постов</Th>
                    <Th>Детейлинг</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.locations.map((r) => (
                    <tr key={r.location.id}>
                      <Td>{r.location.name}</Td>
                      <Td>{formatMoney(r.revenue)}</Td>
                      <Td>{r.orders_closed}</Td>
                      <Td>{formatMoney(r.average_check)}</Td>
                      <Td>{formatPercent(r.post_load)}</Td>
                      <Td>{formatPercent(r.detailing_share)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </section>

          <section aria-label="Топ услуг">
            <h2 className="mb-2 text-base font-semibold">Топ услуг</h2>
            {d.top_services.length === 0 ? (
              <EmptyNote>Нет данных за период</EmptyNote>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Услуга</Th>
                    <Th>Кол-во</Th>
                    <Th>Выручка</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.top_services.map((s, i) => (
                    <tr key={`${s.service_id ?? "x"}-${i}`}>
                      <Td>{s.name}</Td>
                      <Td>{formatQty(s.quantity)}</Td>
                      <Td>{formatMoney(s.revenue)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </section>

          <Attention a={d.attention} />
        </>
      )}
      {!d && !q.error && !q.isLoading && <Skeleton lines={2} />}
    </div>
  );
}
