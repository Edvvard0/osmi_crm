import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { useActiveLocation } from "@/features/locations/api";
import { Skeleton } from "@/features/orders/ui";
import { DEPARTMENT_LABELS } from "@/shared/api/types";
import { formatHours, formatMoney } from "@/shared/lib/money";
import { Badge, Button } from "@/shared/ui/ui";

import { payrollExportPath, usePayroll, usePayrollDetail } from "./api";
import { EmptyNote, QueryError } from "./filters";
import { AdjustmentDialog, SchemesDialog } from "./PayrollDialogs";
import {
  EXPORT_FORMATS,
  downloadFile,
  enc,
  formatDate,
  formatMonth,
  formatQty,
  formatSigned,
  isMonth,
  plural,
  reportErrorText,
  shiftMonth,
  sign,
  useToday,
} from "./lib";
import type { PayrollRow, UserRef } from "./types";

const NUM = "whitespace-nowrap px-3 py-2 text-right tabular-nums";

function Signed({ v }: { v: string }) {
  const s = sign(v);
  return <span className={clsx(s > 0 && "text-success", s < 0 && "text-danger")}>{formatSigned(v)}</span>;
}

function DetailView({ row, month, onAdjust, onSchemes }: { row: PayrollRow; month: string; onAdjust: () => void; onSchemes: () => void }) {
  const q = usePayrollDetail(row.user.id, month, true);
  if (q.isLoading) return <Skeleton lines={3} />;
  if (q.error || !q.data) return <QueryError error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted">{d.row.scheme_summary}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={onAdjust}>Премия / удержание</Button>
          <Button variant="secondary" onClick={onSchemes}>Схемы оплаты</Button>
        </div>
      </div>

      <section aria-label="Работы месяца">
        <h3 className="mb-1 font-medium">Работы</h3>
        {d.items.length === 0 ? (
          <p className="text-muted">Учтённых работ за месяц нет</p>
        ) : (
          <div className="overflow-x-auto rounded border border-border">
            <table className="w-full text-left">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-muted">
                  <th scope="col" className="px-3 py-2 font-medium">Заказ</th>
                  <th scope="col" className="px-3 py-2 font-medium">Работа</th>
                  <th scope="col" className="px-3 py-2 font-medium">Отдел</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Кол-во</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Нормочасы</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Сумма работы</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Начислено</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((it) => (
                  <tr key={it.item_id} className="border-t border-border">
                    <td className="whitespace-nowrap px-3 py-2">
                      <Link to={`/orders/${enc(it.order.id)}`} className="underline underline-offset-2">{it.order.number}</Link>
                      <span className="block text-xs text-muted">{formatDate(it.closed_at.slice(0, 10))}</span>
                    </td>
                    <td className="break-words px-3 py-2">{it.name}</td>
                    <td className="px-3 py-2">{DEPARTMENT_LABELS[it.department]}</td>
                    <td className={NUM}>{formatQty(it.quantity)}</td>
                    <td className={NUM}>{formatHours(it.norm_hours_total)}</td>
                    <td className={NUM}>{formatMoney(it.item_net)}</td>
                    <td className={NUM}>
                      {formatMoney(it.amount)}
                      {it.scheme_id === null && <span className="ml-2"><Badge tone="warning">Без схемы</Badge></span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {d.fixed.length > 0 && (
        <section aria-label="Оклад">
          <h3 className="mb-1 font-medium">Оклад</h3>
          <ul className="space-y-1">
            {d.fixed.map((f) => (
              <li key={f.scheme_id} className="flex flex-wrap justify-between gap-2">
                <span className="text-muted">{f.days} из {f.days_in_month} {plural(f.days_in_month, "дня", "дней", "дней")}</span>
                <span className="tabular-nums">{formatMoney(f.amount)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Корректировки">
        <h3 className="mb-1 font-medium">Премии и удержания</h3>
        {d.adjustments.length === 0 ? (
          <p className="text-muted">За месяц нет</p>
        ) : (
          <ul className="divide-y divide-border rounded border border-border">
            {d.adjustments.map((a) => (
              <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <p className="break-words">{a.reason}</p>
                  <p className="text-xs text-muted">{a.created_by.full_name} · {formatDate(a.created_at.slice(0, 10))}</p>
                </div>
                <span className="whitespace-nowrap tabular-nums"><Signed v={a.amount} /></span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Схемы месяца">
        <h3 className="mb-1 font-medium">Схемы</h3>
        {d.schemes.length === 0 ? (
          <p className="text-muted">Схема не задана</p>
        ) : (
          <ul className="space-y-1">
            {d.schemes.map((s) => (
              <li key={s.id} className="break-words">
                {s.description}
                <span className="text-muted">
                  {" "}· {s.department ? DEPARTMENT_LABELS[s.department] : "все отделы"} · с {formatDate(s.valid_from)}
                  {s.valid_to ? ` по ${formatDate(s.valid_to)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** D-03: зарплатная ведомость за месяц. Точка берётся из переключателя в шапке. */
export function PayrollPage() {
  const today = useToday();
  const currentMonth = today.slice(0, 7);
  const { value: locationId } = useActiveLocation();
  const [month, setMonth] = useState<string | null>(null);
  const m = month ?? currentMonth;
  const q = usePayroll({ month: m, locationId });
  const [open, setOpen] = useState<string | null>(null);
  const [adjust, setAdjust] = useState<{ user: UserRef | null } | null>(null);
  const [schemes, setSchemes] = useState<{ user: UserRef | null } | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const sheet = q.data && q.data.month === m ? q.data : null;
  const noScheme = sheet ? sheet.rows.reduce((n, r) => n + r.items_without_scheme, 0) : 0;
  const next = shiftMonth(m, 1);

  async function doExport(format: string) {
    setExportError(null);
    setExporting(format);
    try {
      await downloadFile(payrollExportPath({ month: m, locationId }, format), `payroll-${m}.${format}`);
    } catch (e) {
      setExportError(reportErrorText(e));
    } finally {
      setExporting(null);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Зарплата</h1>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setAdjust({ user: null })}>Премия / удержание</Button>
          <Button variant="secondary" onClick={() => setSchemes({ user: null })}>Схемы оплаты</Button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Месяц" className="flex items-center gap-1">
          <Button variant="secondary" aria-label="Предыдущий месяц" onClick={() => { setMonth(shiftMonth(m, -1)); setOpen(null); }}><ChevronLeft size={18} aria-hidden="true" /></Button>
          <label className="px-2 text-sm font-medium">
            <span className="sr-only">Месяц ведомости</span>
            <input
              type="month"
              value={m}
              max={currentMonth}
              onChange={(e) => { if (isMonth(e.target.value) && e.target.value <= currentMonth) { setMonth(e.target.value); setOpen(null); } }}
              className="min-h-10 rounded border border-border bg-surface px-2 text-fg"
            />
          </label>
          <Button variant="secondary" aria-label="Следующий месяц" disabled={next > currentMonth} onClick={() => { setMonth(next); setOpen(null); }}><ChevronRight size={18} aria-hidden="true" /></Button>
        </div>
        <p className="text-sm text-muted">{formatMonth(m)}</p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">Экспорт ведомости</span>
          {EXPORT_FORMATS.map((f) => (
            <Button key={f} variant="secondary" loading={exporting === f} disabled={!!exporting || !sheet} onClick={() => void doExport(f)}>
              {f.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>
      {exportError && <p role="alert" className="mt-2 text-sm text-danger">{exportError}</p>}

      <div className="mt-4 space-y-3">
        {q.error && !sheet && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
        {!sheet && !q.error && <Skeleton lines={5} />}
        {sheet && (
          <>
            {q.error && <QueryError error={q.error} onRetry={() => void q.refetch()} />}
            {noScheme > 0 && (
              <p role="status" className="rounded-lg border border-warning/40 p-3 text-sm text-warning">
                Работ без схемы: {noScheme}. Они начислены нулём. Задайте схему оплаты сотруднику.
              </p>
            )}
            {sheet.rows.length === 0 ? (
              <EmptyNote>За выбранный месяц начислений нет</EmptyNote>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border bg-surface">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Ведомость за {formatMonth(m)}</caption>
                  <thead>
                    <tr className="text-xs uppercase tracking-wide text-muted">
                      <th scope="col" className="px-3 py-2 font-medium">Сотрудник</th>
                      <th scope="col" className="px-3 py-2 font-medium">Схема</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Работ</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Нормочасы</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Начислено</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Премии и удержания</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">К выплате</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sheet.rows.map((r) => {
                      const isOpen = open === r.user.id;
                      return (
                        <Fragment key={r.user.id}>
                          <tr className="border-t border-border align-top">
                            <td className="px-3 py-2">
                              <button
                                type="button"
                                aria-expanded={isOpen}
                                onClick={() => setOpen(isOpen ? null : r.user.id)}
                                className="min-h-8 break-words text-left font-medium underline underline-offset-2"
                              >
                                {r.user.full_name}
                              </button>
                              <span className="block text-xs text-muted">{r.locations.map((l) => l.name).join(", ")}</span>
                              {r.items_without_scheme > 0 && <Badge tone="warning">{`Без схемы: ${r.items_without_scheme}`}</Badge>}
                            </td>
                            <td className="break-words px-3 py-2 text-muted">{r.scheme_summary}</td>
                            <td className={NUM}>{r.items_done}</td>
                            <td className={NUM}>{formatHours(r.norm_hours)}</td>
                            <td className={NUM}>{formatMoney(r.accrued)}</td>
                            <td className={NUM}><Signed v={r.adjustments_total} /></td>
                            <td className={clsx(NUM, "font-medium")}>{formatMoney(r.total)}</td>
                          </tr>
                          {isOpen && (
                            <tr className="border-t border-border bg-bg">
                              <td colSpan={7} className="px-3 py-3">
                                <DetailView
                                  row={r}
                                  month={m}
                                  onAdjust={() => setAdjust({ user: r.user })}
                                  onSchemes={() => setSchemes({ user: r.user })}
                                />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-border font-medium">
                      <td className="px-3 py-2">Итого</td>
                      <td />
                      <td className={NUM}>{sheet.totals.items_done}</td>
                      <td className={NUM}>{formatHours(sheet.totals.norm_hours)}</td>
                      <td className={NUM}>{formatMoney(sheet.totals.accrued)}</td>
                      <td className={NUM}><Signed v={sheet.totals.adjustments_total} /></td>
                      <td className={NUM}>{formatMoney(sheet.totals.total)}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {adjust && <AdjustmentDialog month={m} user={adjust.user} onClose={() => setAdjust(null)} />}
      {schemes && <SchemesDialog user={schemes.user} onClose={() => setSchemes(null)} />}
    </div>
  );
}
