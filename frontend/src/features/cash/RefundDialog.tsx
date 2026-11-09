import { useRef, useState } from "react";

import { type AppError, toAppError } from "@/shared/api/errors";
import { formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Alert, Button, Input, Textarea } from "@/shared/ui/ui";

import { type PaymentResult, useRefundPayment } from "./api";
import { cashErrorText, newRequestId, toCents } from "./lib";
import { METHOD_LABELS, type Payment, type PaymentMethod } from "./types";

/** Платёж, по которому оформляется возврат (собирается из Payment или CashOperation). */
export interface RefundTarget {
  id: string;
  orderId: string;
  orderNumber: string;
  method: PaymentMethod;
  amount: string;
  refundable: string;
}

export function refundTargetFromPayment(p: Payment): RefundTarget | null {
  if (p.payment_type !== "payment" || !p.refundable || toCents(p.refundable) <= 0) return null;
  return { id: p.id, orderId: p.work_order_id, orderNumber: p.order_number, method: p.method, amount: p.amount, refundable: p.refundable };
}

/** Возврат по платежу (только директор): сумма ≤ refundable, причина обязательна. */
export function RefundDialog({ target, onClose, onDone }: { target: RefundTarget; onClose: () => void; onDone?: (r: PaymentResult) => void }) {
  const [amount, setAmount] = useState(toInput(target.refundable));
  const [reason, setReason] = useState("");
  const [amountErr, setAmountErr] = useState<string>();
  const [reasonErr, setReasonErr] = useState<string>();
  const reqId = useRef(newRequestId());
  const refund = useRefundPayment(target.id, target.orderId);
  const err: AppError | null = refund.error ? toAppError(refund.error) : null;
  const touch = () => {
    reqId.current = newRequestId();
    setAmountErr(undefined);
    setReasonErr(undefined);
  };

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (refund.isPending) return;
    const dec = parseDecimal(amount);
    const text = reason.trim();
    let bad = false;
    if (!dec || toCents(dec) <= 0) {
      setAmountErr("Введите сумму больше нуля");
      bad = true;
    } else if (toCents(dec) > toCents(target.refundable)) {
      setAmountErr(`Сумма больше доступной к возврату: ${formatMoney(target.refundable)}`);
      bad = true;
    }
    if (text.length < 3) {
      setReasonErr("Укажите причину возврата (от 3 до 500 символов)");
      bad = true;
    }
    if (bad || !dec) return;
    refund.mutate(
      { amount: dec, comment: text, client_request_id: reqId.current },
      {
        onSuccess: (r) => {
          onDone?.(r);
          onClose();
        },
      },
    );
  }

  return (
    <Modal title="Возврат оплаты" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="rounded border border-border bg-bg px-3 py-2 text-sm">
          <div className="flex justify-between gap-2">
            <span className="text-muted">Заказ {target.orderNumber} · {METHOD_LABELS[target.method]}</span>
            <span className="tabular-nums">Оплачено {formatMoney(target.amount)}</span>
          </div>
          <div className="mt-1 flex justify-between gap-2">
            <span className="text-muted">Доступно к возврату</span>
            <strong className="tabular-nums">{formatMoney(target.refundable)}</strong>
          </div>
        </div>
        <Input
          label="Сумма возврата"
          inputMode="decimal"
          autoComplete="off"
          value={amount}
          error={amountErr}
          onChange={(e) => {
            setAmount(e.target.value);
            touch();
          }}
        />
        <Textarea
          label="Причина возврата"
          maxLength={500}
          value={reason}
          error={reasonErr}
          onChange={(e) => {
            setReason(e.target.value);
            touch();
          }}
        />
        {err && <Alert>{err.code === "validation_error" && err.fields.comment ? "Укажите причину возврата (от 3 до 500 символов)" : cashErrorText(err)}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="danger" loading={refund.isPending}>Оформить возврат</Button>
        </div>
      </form>
    </Modal>
  );
}
