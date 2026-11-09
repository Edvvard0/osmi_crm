import { useState } from "react";

import { useLocations } from "@/features/locations/api";
import { useMe } from "@/features/auth/AuthProvider";
import { toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";
import { Alert, Button, Loading } from "@/shared/ui/ui";

import { useOrderPayments } from "./api";
import { PaymentDialog } from "./PaymentDialog";
import { RefundDialog, type RefundTarget, refundTargetFromPayment } from "./RefundDialog";
import { fmtDateTime, toCents } from "./lib";
import { METHOD_LABELS } from "./types";

export interface PaymentsOrder {
  id: string;
  number: string;
  status: string;
  balance_due: string;
  paid_total: string;
}

/**
 * Блок «Оплаты» карточки заказа (MG-05): список платежей и возвратов, «Принять оплату» (MG-14), директору — «Вернуть».
 * Только для manager/director; у механика ничего не рендерится и запросов нет.
 */
export function OrderPayments({ order }: { order: PaymentsOrder }) {
  const me = useMe();
  const allowed = me.role === "manager" || me.role === "director";
  const q = useOrderPayments(order.id, allowed);
  const locs = useLocations();
  const [paying, setPaying] = useState(false);
  const [refund, setRefund] = useState<RefundTarget | null>(null);
  if (!allowed) return null;

  const canPay = order.status !== "cancelled" && toCents(order.balance_due) > 0;
  const tzOf = (locationId: string) => locs.data?.find((l) => l.id === locationId)?.timezone ?? "Europe/Moscow";
  const items = q.data ?? [];

  return (
    <section aria-label="Оплаты" className="space-y-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Оплаты</h2>
        <Button onClick={() => setPaying(true)} disabled={!canPay}>Принять оплату</Button>
      </div>
      <p className="text-sm text-muted">
        Оплачено: <span className="tabular-nums text-fg">{formatMoney(order.paid_total)}</span> · К оплате: <span className="tabular-nums text-fg">{formatMoney(order.balance_due)}</span>
      </p>

      {q.isLoading && <Loading />}
      {q.isError && <Alert>{toAppError(q.error).message}</Alert>}
      {q.isSuccess && items.length === 0 && <p className="text-sm text-muted">Оплат пока нет</p>}
      {items.length > 0 && (
        <ul className="divide-y divide-border text-sm">
          {items.map((p) => {
            const isRefund = p.payment_type === "refund";
            const target = me.role === "director" ? refundTargetFromPayment(p) : null;
            return (
              <li key={p.id} className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2">
                <div className="min-w-0">
                  <div className="font-medium">
                    {isRefund ? "Возврат" : "Оплата"} · {METHOD_LABELS[p.method]}
                  </div>
                  <div className="text-xs text-muted">
                    {fmtDateTime(p.paid_at, tzOf(p.location_id))} · {p.accepted_by.full_name}
                  </div>
                  {p.comment && <div className="text-xs text-muted">{isRefund ? "Причина: " : ""}{p.comment}</div>}
                </div>
                <div className="flex items-center gap-2">
                  <span className={isRefund ? "tabular-nums text-danger" : "tabular-nums text-success"}>
                    {isRefund ? "−" : "+"}{formatMoney(p.amount)}
                  </span>
                  {target && (
                    <Button variant="secondary" className="min-h-8 px-2 text-xs" aria-label={`Вернуть оплату ${formatMoney(p.amount)}`} onClick={() => setRefund(target)}>
                      Вернуть
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {paying && <PaymentDialog order={order} onClose={() => setPaying(false)} />}
      {refund && <RefundDialog target={refund} onClose={() => setRefund(null)} />}
    </section>
  );
}
