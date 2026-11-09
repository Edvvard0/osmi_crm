import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { WorkOrder } from "@/features/orders/types";
import { api } from "@/shared/api/client";
import type { Page } from "@/shared/api/types";

import type { CashKind, CashOperation, CashReport, Expense, ExpenseCategory, ExpensePage, Payment, PaymentMethod } from "./types";

export const CASH_PAGE_SIZE = 50;
const enc = encodeURIComponent;

function qs(o: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/* ---------- Оплаты по заказу ---------- */

export function useOrderPayments(orderId: string, enabled = true) {
  return useQuery({
    queryKey: ["order-payments", orderId],
    queryFn: () => api<Payment[]>(`/work-orders/${enc(orderId)}/payments`),
    enabled: enabled && !!orderId,
  });
}

export interface PaymentResult { payment: Payment; order: WorkOrder }

/** После оплаты/возврата: карточка заказа получает обновлённый заказ, списки и касса перечитываются. */
function useAfterMoney(orderId: string) {
  const qc = useQueryClient();
  return (r: PaymentResult) => {
    qc.setQueryData(["order", orderId], r.order);
    void qc.invalidateQueries({ queryKey: ["order-history", orderId] });
    void qc.invalidateQueries({ queryKey: ["order-payments", orderId] });
    void qc.invalidateQueries({ queryKey: ["orders"] });
    void qc.invalidateQueries({ queryKey: ["cash"] });
  };
}

export interface PayInput { amount: string; method: PaymentMethod; comment?: string; client_request_id: string }
export function usePayOrder(orderId: string) {
  const after = useAfterMoney(orderId);
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: PayInput) => api<PaymentResult>(`/work-orders/${enc(orderId)}/payments`, { body: b }),
    onSuccess: after,
  });
}

export interface RefundInput { amount?: string; comment: string; client_request_id: string }
export function useRefundPayment(paymentId: string, orderId: string) {
  const after = useAfterMoney(orderId);
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: RefundInput) => api<PaymentResult>(`/payments/${enc(paymentId)}/refund`, { body: b }),
    onSuccess: after,
  });
}

/* ---------- Категории и расходы ---------- */

export function useExpenseCategories(includeInactive = false) {
  return useQuery({
    queryKey: ["cash", "categories", includeInactive],
    queryFn: () => api<ExpenseCategory[]>(`/expense-categories${qs({ include_inactive: includeInactive })}`),
  });
}

export function useCreateExpenseCategory() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: { name: string }) => api<ExpenseCategory>("/expense-categories", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cash", "categories"] }),
  });
}

export function useUpdateExpenseCategory(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: { name?: string; is_active?: boolean }) => api<ExpenseCategory>(`/expense-categories/${enc(id)}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cash", "categories"] }),
  });
}

export interface ExpenseInput {
  location_id: string;
  category_id: string;
  amount: string;
  method: PaymentMethod;
  expense_date: string;
  description?: string;
}
export function useCreateExpense() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: ExpenseInput) => api<Expense>("/expenses", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cash"] }),
  });
}

export function useCancelExpense(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: { reason?: string }) => api<Expense>(`/expenses/${enc(id)}/cancel`, { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cash"] }),
  });
}

/** Список расходов (для разделов, которым нужен именно он; касса показывает общий поток операций). */
export function useExpenses(f: { locationId: string; dateFrom: string; dateTo: string; offset: number }, enabled = true) {
  const q = qs({ location_id: f.locationId, date_from: f.dateFrom, date_to: f.dateTo, limit: CASH_PAGE_SIZE, offset: f.offset });
  return useQuery({
    queryKey: ["cash", "expenses", q],
    queryFn: () => api<ExpensePage>(`/expenses${q}`),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/* ---------- Отчёт и операции (MG-13) ---------- */

export interface CashFilters {
  locationId: string;
  dateFrom: string;
  dateTo: string;
  kind: "" | CashKind;
  method: "" | PaymentMethod;
  offset: number;
}

export function useCashReport(f: Pick<CashFilters, "locationId" | "dateFrom" | "dateTo">) {
  const q = qs({ location_id: f.locationId, date_from: f.dateFrom, date_to: f.dateTo });
  return useQuery({ queryKey: ["cash", "report", q], queryFn: () => api<CashReport>(`/cash/report${q}`), enabled: !!f.locationId, placeholderData: keepPreviousData });
}

export function useCashOperations(f: CashFilters) {
  const q = qs({ location_id: f.locationId, date_from: f.dateFrom, date_to: f.dateTo, kind: f.kind, method: f.method, limit: CASH_PAGE_SIZE, offset: f.offset });
  return useQuery({
    queryKey: ["cash", "operations", q],
    queryFn: () => api<Page<CashOperation>>(`/cash/operations${q}`),
    enabled: !!f.locationId,
    placeholderData: keepPreviousData,
  });
}
