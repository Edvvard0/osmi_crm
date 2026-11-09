import { safeZone } from "@/features/appointments/time";
import { type AppError, fieldMessage, messageFor, toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";

/** Деньги в копейках (целое): суммы до 9 цифр помещаются в безопасный диапазон Number. */
export function toCents(v: string | null | undefined): number {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec((v ?? "").trim());
  if (!m) return 0;
  const c = Number(m[2]) * 100 + Number((m[3] ?? "").padEnd(2, "0").slice(0, 2));
  return m[1] ? -c : c;
}
export function fromCents(c: number): string {
  const a = Math.abs(Math.round(c));
  return `${c < 0 ? "-" : ""}${Math.floor(a / 100)}.${String(a % 100).padStart(2, "0")}`;
}
export const isPositive = (v: string | null | undefined) => toCents(v) > 0;

/** ISO-время → "09.11, 13:05" в поясе точки. */
export function fmtDateTime(iso: string, tz: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", { timeZone: safeZone(tz), day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(d);
}

/** Русский текст ошибки кассовой операции; суммы из `details` форматируются здесь. */
export function cashErrorText(e: unknown): string {
  const err: AppError = toAppError(e);
  switch (err.code) {
    case "overpayment":
      return `Сумма больше остатка к оплате: ${formatMoney(err.details.balance_due)}`;
    case "refund_exceeds_payment":
      return `Сумма больше доступной к возврату: ${formatMoney(err.details.refundable)}`;
    case "order_not_paid":
      return err.details.balance_due ? `Заказ не оплачен полностью. Остаток: ${formatMoney(err.details.balance_due)}` : "Заказ не оплачен полностью";
    case "invalid_state":
      return "Операция недоступна: заказ отменён или действие уже выполнено";
    case "forbidden":
      return "Недостаточно прав для этого действия";
    case "validation_error": {
      const texts = Object.keys(err.fields).map((n) => fieldMessage(err, n)).filter(Boolean);
      return texts.length ? texts.join(". ") : messageFor("validation_error");
    }
    default:
      return err.message;
  }
}

export function newRequestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
