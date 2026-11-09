import clsx from "clsx";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { todayIn } from "@/features/appointments/time";
import { useMe } from "@/features/auth/AuthProvider";
import { useActiveLocation } from "@/features/locations/api";
import { toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Alert, Badge, Button, Checkbox, Input, Select, Table, Th } from "@/shared/ui/ui";

import { CASH_PAGE_SIZE, useCancelExpense, useCashOperations, useCashReport } from "./api";
import { ExpenseDialog } from "./ExpenseDialog";
import { RefundDialog, type RefundTarget } from "./RefundDialog";
import { cashErrorText, fmtDateTime, toCents } from "./lib";
import { ALL_METHODS, type CashKind, type CashOperation, type CashReport, KIND_LABELS, METHOD_LABELS, type PaymentMethod } from "./types";

function CancelExpenseDialog({ op, onClose }: { op: CashOperation; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const cancel = useCancelExpense(op.id);
  return (
    <Modal title="Отмена расхода" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (cancel.isPending) return;
          cancel.mutate({ reason: reason.trim() || undefined }, { onSuccess: onClose });
        }}
      >
        <p className="text-sm">
          Расход {formatMoney(op.amount)}{op.category ? ` · ${op.category.name}` : ""} будет отменён и исключён из итогов. Исправить расход нельзя — введите его заново.
        </p>
        <Input label="Причина (необязательно)" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
        {cancel.error != null && <Alert>{cashErrorText(cancel.error)}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Не отменять</Button>
          <Button type="submit" variant="danger" loading={cancel.isPending}>Отменить расход</Button>
        </div>
      </form>
    </Modal>
  );
}

function Skeleton() {
  return (
    <div role="status" aria-label="Загрузка кассы" className="grid animate-pulse gap-4 lg:grid-cols-3">
      <div className="h-44 rounded-lg bg-border/50 lg:col-span-2" />
      <div className="h-44 rounded-lg bg-border/50" />
      <div className="h-48 rounded-lg bg-border/50 lg:col-span-3" />
    </div>
  );
}

function Summary({ r }: { r: CashReport }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <section aria-label="Итоги по способам оплаты" className="rounded-lg border border-border bg-surface p-4 lg:col-span-2">
        <h2 className="mb-2 text-base font-semibold">Оплаты по способам</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-muted">
                <th scope="col" className="py-1 pr-3 font-medium">Способ</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">Получено</th>
                <th scope="col" className="py-1 pr-3 text-right font-medium">Возвраты</th>
                <th scope="col" className="py-1 text-right font-medium">Итого</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {r.payments.map((m) => (
                <tr key={m.method} className="border-t border-border">
                  <th scope="row" className="py-1.5 pr-3 font-normal">{METHOD_LABELS[m.method]}</th>
                  <td className="py-1.5 pr-3 text-right">{formatMoney(m.received)}</td>
                  <td className="py-1.5 pr-3 text-right">{toCents(m.refunded) > 0 ? `−${formatMoney(m.refunded)}` : formatMoney(m.refunded)}</td>
                  <td className="py-1.5 text-right">{formatMoney(m.net)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="tabular-nums">
              <tr className="border-t border-border font-semibold">
                <th scope="row" className="py-1.5 pr-3">Всего</th>
                <td className="py-1.5 pr-3 text-right">{formatMoney(r.received_total)}</td>
                <td className="py-1.5 pr-3 text-right">{toCents(r.refunded_total) > 0 ? `−${formatMoney(r.refunded_total)}` : formatMoney(r.refunded_total)}</td>
                <td className="py-1.5 text-right">{formatMoney(r.net_total)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <div className="space-y-4">
        <section aria-label="Остаток наличных" className="rounded-lg border border-border bg-surface p-4">
          <h2 className="text-sm text-muted">Остаток наличных за период</h2>
          <p className={clsx("mt-1 text-2xl font-semibold tabular-nums", toCents(r.cash_balance) < 0 && "text-danger")} data-testid="cash-balance">
            {formatMoney(r.cash_balance)}
          </p>
          <p className="mt-1 text-xs text-muted">Движение наличных за период, а не сумма в кассе</p>
        </section>
        <section aria-label="Расходы" className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold">Расходы</h2>
            <strong className="tabular-nums" data-testid="expenses-total">{formatMoney(r.expenses_total)}</strong>
          </div>
          {r.expenses_by_category.length === 0 ? (
            <p className="mt-2 text-sm text-muted">Расходов нет</p>
          ) : (
            <ul className="mt-2 space-y-1 text-sm">
              {r.expenses_by_category.map((c) => (
                <li key={c.category.id} className="flex justify-between gap-2">
                  <span className="min-w-0 truncate">{c.category.name}</span>
                  <span className="tabular-nums">{formatMoney(c.total)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

function OperationRow({ op, tz, isDirector, onRefund, onCancel }: { op: CashOperation; tz: string; isDirector: boolean; onRefund: (o: CashOperation) => void; onCancel: (o: CashOperation) => void }) {
  const positive = op.kind === "payment";
  const struck = op.is_cancelled;
  return (
    <tr className={clsx("border-b border-border last:border-0", struck && "text-muted")} data-kind={op.kind}>
      <td className="whitespace-nowrap px-3 py-2">{fmtDateTime(op.at, tz)}</td>
      <td className="px-3 py-2">
        <span className={clsx("font-medium", op.kind === "payment" && "text-success", op.kind === "refund" && "text-danger", struck && "line-through")}>{KIND_LABELS[op.kind]}</span>
        {struck && <span className="ml-2"><Badge>Отменён</Badge></span>}
      </td>
      <td className="px-3 py-2">{METHOD_LABELS[op.method]}</td>
      <td className="max-w-[18rem] px-3 py-2">
        <span className={clsx(struck && "line-through")}>
          {op.order ? <Link to={`/orders/${op.order.id}`} className="underline">{op.order.number}</Link> : op.category?.name}
        </span>
        {op.comment && <span className="block truncate text-xs text-muted">{op.comment}</span>}
        <span className="block text-xs text-muted">{op.user.full_name}</span>
      </td>
      <td className={clsx("whitespace-nowrap px-3 py-2 text-right tabular-nums", positive ? "text-success" : "text-danger", struck && "line-through text-muted")}>
        {positive ? "+" : "−"}{formatMoney(op.amount)}
      </td>
      <td className="px-3 py-2 text-right">
        {isDirector && op.kind === "payment" && op.refundable && toCents(op.refundable) > 0 && (
          <Button variant="secondary" className="min-h-8 px-2 text-xs" aria-label={`Вернуть оплату ${op.order?.number ?? ""} ${formatMoney(op.amount)}`} onClick={() => onRefund(op)}>
            Вернуть
          </Button>
        )}
        {isDirector && op.kind === "expense" && !op.is_cancelled && (
          <Button variant="secondary" className="min-h-8 px-2 text-xs" aria-label={`Отменить расход ${formatMoney(op.amount)}`} onClick={() => onCancel(op)}>
            Отменить
          </Button>
        )}
      </td>
    </tr>
  );
}

/** MG-13 «Касса» */
export function CashPage() {
  const me = useMe();
  const isDirector = me.role === "director";
  const loc = useActiveLocation();
  const [sp, setSp] = useSearchParams();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [period, setPeriod] = useState(false);
  const [kind, setKind] = useState<"" | CashKind>("");
  const [method, setMethod] = useState<"" | PaymentMethod>("");
  const [offset, setOffset] = useState(0);
  const [expenseOpen, setExpenseOpen] = useState(false);
  const [refund, setRefund] = useState<RefundTarget | null>(null);
  const [cancel, setCancel] = useState<CashOperation | null>(null);

  const param = sp.get("location_id") ?? "";
  const locationId = loc.items.some((l) => l.id === param) ? param : loc.value !== "all" ? loc.value : (loc.items[0]?.id ?? "");
  const location = loc.items.find((l) => l.id === locationId);
  const tz = location?.timezone ?? "Europe/Moscow";
  const from = dateFrom || todayIn(tz, Date.now());
  const to = period ? dateTo || from : from;

  const report = useCashReport({ locationId, dateFrom: from, dateTo: to });
  const ops = useCashOperations({ locationId, dateFrom: from, dateTo: to, kind, method, offset });
  const refetch = () => {
    void report.refetch();
    void ops.refetch();
  };

  const items = ops.data?.items ?? [];
  const total = ops.data?.total ?? 0;
  const failed = (report.isError && !report.data) || (ops.isError && !ops.data);
  const loading = !failed && (loc.loading || (!!locationId && (!report.data || !ops.data)));
  const reportTz = report.data?.timezone ?? tz;
  const reset = () => setOffset(0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Касса</h1>
        <Button onClick={() => setExpenseOpen(true)} disabled={!locationId}>Расход</Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Select
          label="Точка"
          value={locationId}
          onChange={(e) => {
            setSp({ location_id: e.target.value });
            reset();
          }}
        >
          {loc.items.map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </Select>
        <Input
          label={period ? "С" : "Дата"}
          type="date"
          value={from}
          onChange={(e) => {
            setDateFrom(e.target.value);
            reset();
          }}
        />
        {period && (
          <Input
            label="По"
            type="date"
            value={to}
            min={from}
            onChange={(e) => {
              setDateTo(e.target.value);
              reset();
            }}
          />
        )}
        <div className="flex items-end">
          <Checkbox
            label="Период"
            checked={period}
            onChange={(e) => {
              setPeriod(e.target.checked);
              reset();
            }}
          />
        </div>
      </div>

      {failed && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <span>Не удалось загрузить кассу{report.error || ops.error ? `. ${toAppError(report.error ?? ops.error).message}` : ""}</span>
          <Button variant="secondary" onClick={refetch}>Повторить</Button>
        </div>
      )}
      {loading && <Skeleton />}
      {!loading && !failed && report.data && <Summary r={report.data} />}

      {!failed && !loading && (
        <section aria-label="Операции" className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-base font-semibold">Операции</h2>
            <div className="grid grid-cols-2 gap-3">
              <Select
                label="Тип"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as "" | CashKind);
                  reset();
                }}
              >
                <option value="">Все</option>
                {(Object.keys(KIND_LABELS) as CashKind[]).map((k) => (
                  <option key={k} value={k}>{KIND_LABELS[k]}</option>
                ))}
              </Select>
              <Select
                label="Способ"
                value={method}
                onChange={(e) => {
                  setMethod(e.target.value as "" | PaymentMethod);
                  reset();
                }}
              >
                <option value="">Все</option>
                {ALL_METHODS.map((m) => (
                  <option key={m} value={m}>{METHOD_LABELS[m]}</option>
                ))}
              </Select>
            </div>
          </div>

          {items.length === 0 ? (
            <p className="rounded-lg border border-border bg-surface px-4 py-8 text-center text-sm text-muted">
              {from === to ? "Операций за выбранный день нет" : "Операций за выбранный период нет"}
            </p>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Время</Th>
                  <Th>Тип</Th>
                  <Th>Способ</Th>
                  <Th>Основание</Th>
                  <Th><span className="block text-right">Сумма</span></Th>
                  <Th><span className="sr-only">Действия</span></Th>
                </tr>
              </thead>
              <tbody>
                {items.map((op) => (
                  <OperationRow
                    key={`${op.kind}-${op.id}`}
                    op={op}
                    tz={reportTz}
                    isDirector={isDirector}
                    onRefund={(o) =>
                      o.order && o.refundable && setRefund({ id: o.id, orderId: o.order.id, orderNumber: o.order.number, method: o.method, amount: o.amount, refundable: o.refundable })
                    }
                    onCancel={setCancel}
                  />
                ))}
              </tbody>
            </Table>
          )}
          {total > CASH_PAGE_SIZE && (
            <div className="flex items-center justify-between text-sm text-muted">
              <span>{offset + 1}–{Math.min(offset + CASH_PAGE_SIZE, total)} из {total}</span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - CASH_PAGE_SIZE))}>Назад</Button>
                <Button variant="secondary" disabled={offset + CASH_PAGE_SIZE >= total} onClick={() => setOffset(offset + CASH_PAGE_SIZE)}>Вперёд</Button>
              </div>
            </div>
          )}
        </section>
      )}

      {expenseOpen && locationId && <ExpenseDialog locationId={locationId} timezone={tz} isDirector={isDirector} onClose={() => setExpenseOpen(false)} />}
      {refund && <RefundDialog target={refund} onClose={() => setRefund(null)} />}
      {cancel && <CancelExpenseDialog op={cancel} onClose={() => setCancel(null)} />}
    </div>
  );
}
