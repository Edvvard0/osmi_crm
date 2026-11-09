import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useLocations } from "@/features/locations/api";
import { api } from "@/shared/api/client";
import { type AppError, fieldMessage, messageFor, toAppError } from "@/shared/api/errors";
import type { Page, Part, Service, User } from "@/shared/api/types";

import type {
  OrderBoard,
  OrderSummary,
  StatusHistoryEntry,
  WorkOrder,
  WorkOrderComment,
  WorkOrderDepartment,
  WorkOrderListItem,
  WorkOrderStatus,
} from "./types";

export const ORDERS_PAGE_SIZE = 50;

export function qs(o: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
const enc = encodeURIComponent;

/* ---------- Списки ---------- */

export interface OrderFilters {
  locationId: string;
  status: WorkOrderStatus[];
  department: "" | WorkOrderDepartment;
  mechanicId: string;
  dateFrom: string;
  dateTo: string;
  overdue: boolean;
  search: string;
  offset: number;
}
export const EMPTY_FILTERS: OrderFilters = { locationId: "", status: [], department: "", mechanicId: "", dateFrom: "", dateTo: "", overdue: false, search: "", offset: 0 };

export function useOrders(f: OrderFilters) {
  const q = qs({
    location_id: f.locationId,
    status: f.status.join(","),
    department: f.department,
    mechanic_id: f.mechanicId,
    date_from: f.dateFrom,
    date_to: f.dateTo,
    overdue: f.overdue,
    search: f.search,
    limit: ORDERS_PAGE_SIZE,
    offset: f.offset,
  });
  return useQuery({
    queryKey: ["orders", "list", q],
    queryFn: () => api<Page<WorkOrderListItem>>(`/work-orders${q}`),
    placeholderData: keepPreviousData,
  });
}

export function useOrderBoard(f: OrderFilters, enabled: boolean) {
  const q = qs({ location_id: f.locationId, department: f.department, mechanic_id: f.mechanicId, overdue: f.overdue });
  return useQuery({
    queryKey: ["orders", "board", q],
    queryFn: () => api<OrderBoard>(`/work-orders/board${q}`),
    enabled,
  });
}

export function useOrderSummary(locationId: string, enabled = true) {
  const q = qs({ location_id: locationId });
  return useQuery({ queryKey: ["orders", "summary", q], queryFn: () => api<OrderSummary>(`/work-orders/summary${q}`), enabled });
}

/** История заказов клиента/авто (MG-09, MG-10). */
export function useEntityOrders(kind: "clients" | "vehicles", id: string, offset: number, limit = 20) {
  const q = qs({ limit, offset });
  return useQuery({
    queryKey: ["orders", "of", kind, id, q],
    queryFn: () => api<Page<WorkOrderListItem>>(`/${kind}/${enc(id)}/work-orders${q}`),
    placeholderData: keepPreviousData,
  });
}

/* ---------- Карточка ---------- */

export function useOrder(id: string | undefined) {
  return useQuery({
    queryKey: ["order", id],
    queryFn: () => api<WorkOrder>(`/work-orders/${enc(id ?? "")}`),
    enabled: !!id,
  });
}

export function useOrderHistory(id: string) {
  return useQuery({ queryKey: ["order-history", id], queryFn: () => api<StatusHistoryEntry[]>(`/work-orders/${enc(id)}/history`) });
}

export function useOrderComments(id: string, internal: boolean) {
  return useQuery({
    queryKey: ["order-comments", id, internal],
    queryFn: () => api<WorkOrderComment[]>(`/work-orders/${enc(id)}/comments?is_internal=${internal}`),
  });
}

export function useAddComment(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: { text: string; is_internal: boolean; item_id?: string }) => api<WorkOrderComment>(`/work-orders/${enc(id)}/comments`, { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["order-comments", id] }),
  });
}

export interface OrderCall {
  /** Путь внутри заказа: "", "/status", "/items", "/items/{id}"… */
  path: string;
  method?: "POST" | "PATCH" | "DELETE";
  body?: Record<string, unknown>;
}

/** Любое изменение заказа: ответ — полный WorkOrder, кладётся в кэш карточки; списки и счётчики обновляются. */
export function useOrderCall(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (c: OrderCall) => api<WorkOrder>(`/work-orders/${enc(id)}${c.path}`, { method: c.method ?? "POST", body: c.body }),
    onSuccess: (o) => {
      qc.setQueryData(["order", id], o);
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["order-history", id] });
      void qc.invalidateQueries({ queryKey: ["appointments"] });
    },
  });
}

/** Смена статуса из канбана (по произвольному заказу). */
export function useChangeOrderStatus() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; version: number; status: WorkOrderStatus }) =>
      api<WorkOrder>(`/work-orders/${enc(v.id)}/status`, { body: { version: v.version, status: v.status } }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["order"] });
    },
  });
}

export interface OrderCreate {
  location_id: string;
  client_id: string;
  vehicle_id: string;
  appointment_id?: string;
  department?: "service" | "detailing";
  mileage_in?: number | null;
  complaint?: string | null;
  intake_notes?: string | null;
  planned_ready_at?: string | null;
  discount_percent?: string;
  items?: Record<string, unknown>[];
}

export function useCreateOrder() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: OrderCreate) => api<WorkOrder>("/work-orders", { body: b }),
    onSuccess: (o) => {
      qc.setQueryData(["order", o.id], o);
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["appointments"] });
    },
  });
}

/* ---------- Справочники для форм ---------- */

export function useCatalogServices(locationId: string, search: string, enabled = true) {
  const q = qs({ location_id: locationId, search, is_active: true, limit: 12 });
  return useQuery({ queryKey: ["orders", "catalog-services", q], queryFn: () => api<Page<Service>>(`/services${q}`), enabled: enabled && !!locationId });
}

export function useCatalogParts(search: string, enabled = true) {
  const q = qs({ search, is_active: true, limit: 12 });
  return useQuery({ queryKey: ["orders", "catalog-parts", q], queryFn: () => api<Page<Part>>(`/parts${q}`), enabled });
}

/** Механики точки. Список сотрудников по контракту доступен руководителю; у менеджера (403) выбор механика скрывается. */
export function useMechanics(locationId: string) {
  const q = qs({ role: "mechanic", is_active: true, location_id: locationId, limit: 200 });
  return useQuery({
    queryKey: ["orders", "mechanics", q],
    queryFn: () => api<Page<User>>(`/users${q}`),
    enabled: !!locationId,
    retry: false,
    select: (p) => p.items,
  });
}

/** Часовой пояс точки заказа (для отображения сроков). */
export function useLocationTz(locationId: string | undefined): string {
  const q = useLocations();
  return q.data?.find((l) => l.id === locationId)?.timezone ?? "Europe/Moscow";
}

/* ---------- Ошибки ---------- */

/** Русский текст ошибки в контексте заказа (общие тексты invalid_state/invalid_transition относятся к записям). */
export function orderErrorText(e: unknown): string {
  const err: AppError = toAppError(e);
  switch (err.code) {
    case "invalid_state":
      return "Действие недоступно в текущем статусе заказа";
    case "invalid_transition":
      return "Недопустимая смена статуса заказа";
    case "forbidden":
      return "Недостаточно прав для этого действия";
    case "items_not_done":
      return err.details.pending_count ? `Не все работы выполнены (осталось: ${err.details.pending_count})` : err.message;
    case "validation_error": {
      const texts = Object.keys(err.fields).map((n) => fieldMessage(err, n)).filter(Boolean);
      return texts.length ? texts.join(". ") : messageFor("validation_error");
    }
    default:
      return err.message;
  }
}

export function useDuplicateOrder(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: () => api<WorkOrder>(`/work-orders/${enc(id)}/duplicate`, { body: {} }),
    onSuccess: (o) => {
      qc.setQueryData(["order", o.id], o);
      void qc.invalidateQueries({ queryKey: ["orders"] });
    },
  });
}
