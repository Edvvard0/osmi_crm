import type { Page } from "@/shared/api/types";

/* Модуль 9: касса. Деньги — строки-десятичные (Money/SignedMoney), см. api-contract-m9.md. */

export type PaymentMethod = "cash" | "card" | "transfer" | "other";
export type PaymentType = "payment" | "refund";
export type CashKind = "payment" | "refund" | "expense";

export interface UserRef { id: string; full_name: string }
export interface IdName { id: string; name: string }

export const METHOD_LABELS: Record<PaymentMethod, string> = { cash: "Наличные", card: "Карта", transfer: "Перевод", other: "Другое" };
/** В диалоге приёма оплаты предлагаются первые три способа. */
export const PAY_METHODS: PaymentMethod[] = ["cash", "card", "transfer"];
export const ALL_METHODS: PaymentMethod[] = ["cash", "card", "transfer", "other"];
export const KIND_LABELS: Record<CashKind, string> = { payment: "Оплата", refund: "Возврат", expense: "Расход" };

export interface Payment {
  id: string;
  work_order_id: string;
  order_number: string;
  location_id: string;
  payment_type: PaymentType;
  amount: string;
  method: PaymentMethod;
  paid_at: string;
  refund_of_id: string | null;
  refundable: string | null;
  comment: string | null;
  accepted_by: UserRef;
  created_at: string;
}

export interface ExpenseCategory { id: string; name: string; is_active: boolean }

export interface Expense {
  id: string;
  location_id: string;
  category: IdName;
  amount: string;
  method: PaymentMethod;
  expense_date: string;
  description: string | null;
  created_by: UserRef;
  created_at: string;
  cancelled_at: string | null;
  cancelled_by: UserRef | null;
}

export interface ExpensePage extends Page<Expense> { total_amount: string }

export interface CashOperation {
  kind: CashKind;
  id: string;
  at: string;
  method: PaymentMethod;
  amount: string;
  signed_amount: string;
  order: { id: string; number: string } | null;
  category: IdName | null;
  comment: string | null;
  user: UserRef;
  is_cancelled: boolean;
  refundable: string | null;
}

export interface MethodTotals { method: PaymentMethod; received: string; refunded: string; net: string }

export interface CashReport {
  location_id: string;
  date_from: string;
  date_to: string;
  timezone: string;
  payments: MethodTotals[];
  received_total: string;
  refunded_total: string;
  net_total: string;
  expenses_by_method: { method: PaymentMethod; total: string }[];
  expenses_by_category: { category: IdName; total: string }[];
  expenses_total: string;
  cash_balance: string;
}
