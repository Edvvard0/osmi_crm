import clsx from "clsx";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { isDateStr } from "@/features/appointments/time";
import { useActiveLocation } from "@/features/locations/api";
import { Skeleton } from "@/features/orders/ui";
import { toAppError } from "@/shared/api/errors";
import { formatHours, formatMoney } from "@/shared/lib/money";
import { Button, Select } from "@/shared/ui/ui";

import { reportExportPath, useReport, type ReportParams } from "./api";
import { BarChart, LineChart } from "./charts";
import { EmptyNote, PeriodFilter, QueryError, usePeriod } from "./filters";
import {
  EXPORT_FORMATS,
  downloadFile,
  enc,
  firstOfMonth,
  formatCell,
  formatDate,
  formatPercent,
  formatQty,
  lastOfMonth,
  monthOf,
  num,
} from "./lib";
import type { Report, ReportColumnKind, ReportId } from "./types";

const REPORTS: { id: ReportId; title: string }[] = [
  { id: "revenue", title: "Выручка" },
  { id: "services", title: "Услуги" },
  { id: "mechanics", title: "Механики" },
  { id: "clients", title: "Клиенты" },
  { id: "stock", title: "Склад" },
  { id: "expenses", title: "Расходы" },
  { id: "profit", title: "Прибыль" },
];

const GROUPS: Partial<Record<ReportId, { value: string; label: string }[]>> = {
  revenue: [
    { value: "location", label: "По точкам" },
    { value: "day", label: "По дням" },
    { value: "month", label: "По месяцам" },
  ],
  clients: [
    { value: "location", label: "По точкам" },
    { value: "month", label: "По месяцам" },
  ],
  expenses: [
    { value: "category", label: "По категориям" },
    { value: "location", label: "По точкам" },
    { value: "month", label: "По месяцам" },
  ],
};

const HAS_DEPARTMENT: ReportId[] = ["services", "mechanics"];
const isReportId = (s: string | null): s is ReportId => REPORTS.some((r) => r.id === s);

/** Ключ строки, содержащий id сущности для ссылки из колонки. Ссылки есть только на карточку механика. */
const LINK_KEYS: Record<string, { idKey: string; href: (id: string) => string }> = {
  mechanic: { idKey: "user_id", href: (id) => `/mechanics/${enc(id)}` },
};

function chartAxis(kind: ReportColumnKind | undefined): (v: number) => string {
  switch (kind) {
    case "money": return (v) => formatMoney(v.toFixed(2));
    case "percent": return (v) => formatPercent(v.toFixed(2));
    case "hours": return (v) => formatHours(v.toFixed(2));
    default: return (v) => formatQty(String(Math.round(v * 1000) / 1000));
  }
}

const categoryLabel = (v: string | null | undefined): string => (v && isDateStr(v) ? formatDate(v).slice(0, 5) : (v ?? "—"));

function ReportChart({ report }: { report: Report }) {
  const c = report.chart;
  if (!c || report.rows.length === 0) return null;
  const kinds = new Map(report.columns.map((col) => [col.key, col.kind]));
  const series = c.series.map((s) => ({ key: s.key, title: s.title, values: report.rows.map((r) => num(r[s.key])) }));
  const Chart = c.type === "line" && report.rows.length > 1 ? LineChart : BarChart;
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <Chart categories={report.rows.map((r) => categoryLabel(r[c.x]))} series={series} format={chartAxis(kinds.get(c.series[0]?.key ?? ""))} label={`График: ${report.title}`} />
    </div>
  );
}

function ReportTable({ report }: { report: Report }) {
  const numeric = (k: ReportColumnKind) => k !== "text" && k !== "date";
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{report.title}</caption>
        <thead>
          <tr>
            {report.columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={clsx("border-b border-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted", numeric(c.kind) && "text-right")}
              >
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row, i) => (
            <tr key={i}>
              {report.columns.map((c) => {
                const link = LINK_KEYS[c.key];
                const id = link ? row[link.idKey] : null;
                const text = formatCell(row[c.key], c.kind);
                return (
                  <td key={c.key} className={clsx("border-b border-border px-3 py-2", numeric(c.kind) ? "whitespace-nowrap text-right tabular-nums" : "break-words")}>
                    {link && id ? (
                      <Link to={link.href(id)} className="underline underline-offset-2">{text}</Link>
                    ) : (
                      text
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        {report.totals && (
          <tfoot>
            <tr className="font-medium">
              {report.columns.map((c, i) => (
                <td key={c.key} className={clsx("px-3 py-2", numeric(c.kind) ? "whitespace-nowrap text-right tabular-nums" : "break-words")}>
                  {i === 0 ? "Итого" : formatCell(report.totals?.[c.key], c.kind)}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

/** D-02: отчёты. Параметры (точка — из переключателя в шапке, период, отдел, группировка) и результат на одном экране. */
export function ReportsPage() {
  const [sp] = useSearchParams();
  const { value: locationId } = useActiveLocation();
  const initialId = sp.get("report");
  const df = sp.get("date_from");
  const dt = sp.get("date_to");
  const initialRange = df && dt && isDateStr(df) && isDateStr(dt) && df <= dt ? { from: df, to: dt } : undefined;

  const [id, setId] = useState<ReportId>(isReportId(initialId) ? initialId : "revenue");
  const period = usePeriod("month", initialRange);
  const [department, setDepartment] = useState<"" | "service" | "detailing">("");
  const [groupBy, setGroupBy] = useState<Record<string, string>>({});
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const groups = GROUPS[id];
  const group = groups ? (groupBy[id] ?? groups[0].value) : "";

  const profit = id === "profit";
  const dateFrom = profit ? firstOfMonth(period.from) : period.from;
  const dateTo = profit ? lastOfMonth(monthOf(period.to)) : period.to;
  const params: ReportParams = { id, locationId, department: HAS_DEPARTMENT.includes(id) ? department : "", dateFrom, dateTo, groupBy: group };

  const q = useReport(params);
  const report = q.data && q.data.id === id ? q.data : null;

  async function doExport(format: string) {
    setExportError(null);
    setExporting(format);
    try {
      await downloadFile(reportExportPath(params, format), `report-${id}-${dateFrom}_${dateTo}.${format}`);
    } catch (e) {
      setExportError(toAppError(e).message);
    } finally {
      setExporting(null);
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold">Отчёты</h1>
      <div className="mt-4 grid gap-5 md:grid-cols-[13rem_minmax(0,1fr)]">
        <nav aria-label="Список отчётов">
          <ul className="flex flex-wrap gap-2 md:flex-col md:gap-1">
            {REPORTS.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  aria-current={r.id === id ? "page" : undefined}
                  onClick={() => { setId(r.id); setExportError(null); }}
                  className={clsx(
                    "min-h-10 w-full rounded border px-3 text-left text-sm",
                    r.id === id ? "border-accent bg-accent text-accent-fg" : "border-border bg-surface text-fg hover:bg-bg",
                  )}
                >
                  {r.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <PeriodFilter period={period} idPrefix="rep" />
            {groups && (
              <div className="w-44">
                <Select label="Группировка" value={group} onChange={(e) => setGroupBy({ ...groupBy, [id]: e.target.value })}>
                  {groups.map((g) => (
                    <option key={g.value} value={g.value}>{g.label}</option>
                  ))}
                </Select>
              </div>
            )}
            {HAS_DEPARTMENT.includes(id) && (
              <div className="w-44">
                <Select label="Отдел" value={department} onChange={(e) => setDepartment(e.target.value as "" | "service" | "detailing")}>
                  <option value="">Все отделы</option>
                  <option value="service">Сервис</option>
                  <option value="detailing">Детейлинг</option>
                </Select>
              </div>
            )}
          </div>
          {profit && (
            <p className="text-xs text-muted">
              Отчёт «Прибыль» строится по целым месяцам: {formatDate(dateFrom)} — {formatDate(dateTo)}.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {EXPORT_FORMATS.map((f) => (
              <Button key={f} variant="secondary" loading={exporting === f} disabled={!!exporting || !report} onClick={() => void doExport(f)}>
                {f.toUpperCase()}
              </Button>
            ))}
            {exportError && <p role="alert" className="text-sm text-danger">{exportError}</p>}
          </div>

          {q.error && !report && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
          {!report && !q.error && <Skeleton lines={5} />}
          {report && (
            <section aria-label={report.title} className="space-y-4">
              <h2 className="text-base font-semibold">{report.title}</h2>
              {q.error && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
              {report.rows.length === 0 ? (
                <EmptyNote>За выбранный период данных нет</EmptyNote>
              ) : (
                <>
                  <ReportChart report={report} />
                  <ReportTable report={report} />
                </>
              )}
              {report.truncated && <p className="text-xs text-muted">Показаны первые 500 строк</p>}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
