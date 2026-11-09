import clsx from "clsx";
import { useRef, useState } from "react";

import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Alert, Button, Input } from "@/shared/ui/ui";

import { type PaymentResult, usePayOrder } from "./api";
import { fromCents, cashErrorText, newRequestId, toCents } from "./lib";
import { METHOD_LABELS, PAY_METHODS, type PaymentMethod } from "./types";

/** Минимум, который нужен диалогу от заказа (подходит и WorkOrder, и WorkOrderListItem). */
export interface PayableOrder { id: string; number: string; balance_due: string }

/** Выбор способа оплаты кнопками. */
export function MethodButtons({ value, onChange, methods = PAY_METHODS }: { value: PaymentMethod; onChange: (m: PaymentMethod) => void; methods?: PaymentMethod[] }) {
  return (
    <div role="group" aria-label="Способ оплаты" className="grid grid-cols-3 gap-2">
      {methods.map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={value === m}
          onClick={() => onChange(m)}
          className={clsx(
            "min-h-10 rounded border px-2 text-sm font-medium",
            value === m ? "border-accent bg-accent text-accent-fg" : "border-border bg-surface text-fg hover:bg-bg",
          )}
        >
          {METHOD_LABELS[m]}
        </button>
      ))}
    </div>
  );
}

/**
 * MG-14 «Приём оплаты». Рендерится только пока открыт (условно: `{open && <PaymentDialog … />}`).
 * Двойная отправка блокируется, каждая отправка несёт `client_request_id` (меняется при изменении полей).
 */
export function PaymentDialog({ order, onClose, onPaid }: { order: PayableOrder; onClose: () => void; onPaid?: (r: PaymentResult) => void }) {
  const [amount, setAmount] = useState(toInput(order.balance_due));
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [received, setReceived] = useState("");
  const [comment, setComment] = useState("");
  const [localErr, setLocalErr] = useState<string>();
  const reqId = useRef(newRequestId());
  const pay = usePayOrder(order.id);
  const touch = () => {
    reqId.current = newRequestId();
    setLocalErr(undefined);
  };

  const err: AppError | null = pay.error ? toAppError(pay.error) : null;
  const fieldErrs = err?.code === "validation_error" && Object.keys(err.fields).length > 0;
  const amountErr = localErr ?? (fieldErrs ? fieldMessage(err, "amount") : undefined);

  const amountDec = parseDecimal(amount);
  const receivedDec = parseDecimal(received);
  const diff = method === "cash" && amountDec && receivedDec ? toCents(receivedDec) - toCents(amountDec) : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pay.isPending) return;
    if (!amountDec || toCents(amountDec) <= 0) {
      setLocalErr("Введите сумму больше нуля");
      return;
    }
    pay.mutate(
      { amount: amountDec, method, comment: comment.trim() || undefined, client_request_id: reqId.current },
      {
        onSuccess: (r) => {
          onPaid?.(r);
          onClose();
        },
      },
    );
  }

  return (
    <Modal title="Приём оплаты" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="flex items-baseline justify-between gap-2 rounded border border-border bg-bg px-3 py-2">
          <span className="text-sm text-muted">Заказ {order.number} · к оплате</span>
          <strong className="text-lg tabular-nums" data-testid="balance-due">{formatMoney(order.balance_due)}</strong>
        </div>

        <Input
          label="Сумма"
          inputMode="decimal"
          autoComplete="off"
          value={amount}
          error={amountErr}
          onChange={(e) => {
            setAmount(e.target.value);
            touch();
          }}
        />

        <div>
          <span className="mb-1 block text-sm text-muted">Способ оплаты</span>
          <MethodButtons
            value={method}
            onChange={(m) => {
              setMethod(m);
              touch();
            }}
          />
        </div>

        {method === "cash" && (
          <div className="space-y-1">
            <Input label="Получено" inputMode="decimal" autoComplete="off" value={received} onChange={(e) => setReceived(e.target.value)} />
            {diff !== null && (
              <p className="text-sm" aria-live="polite">
                {diff >= 0 ? (
                  <>Сдача: <strong className="tabular-nums">{formatMoney(fromCents(diff))}</strong></>
                ) : (
                  <span className="text-muted">Не хватает: {formatMoney(fromCents(-diff))}</span>
                )}
              </p>
            )}
          </div>
        )}

        <Input
          label="Комментарий (необязательно)"
          maxLength={500}
          value={comment}
          error={fieldErrs ? fieldMessage(err, "comment") : undefined}
          onChange={(e) => {
            setComment(e.target.value);
            touch();
          }}
        />

        {err && !fieldErrs && <Alert>{cashErrorText(err)}</Alert>}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={pay.isPending}>Принять оплату</Button>
        </div>
      </form>
    </Modal>
  );
}
