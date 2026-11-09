import { Circle, CircleCheck, CirclePause, CirclePlay, CircleX, type LucideIcon } from "lucide-react";

import type { Department } from "@/shared/api/types";

/* Модуль 5: заказ-наряды. Деньги, часы и количества — строки-десятичные (см. api-contract-m5.md). */

export type WorkOrderStatus =
  | "new"
  | "diagnostics"
  | "awaiting_approval"
  | "in_progress"
  | "awaiting_parts"
  | "quality_check"
  | "ready"
  | "closed"
  | "cancelled";
export type WorkOrderDepartment = "service" | "detailing" | "mixed";
export type ItemStatus = "pending" | "in_progress" | "paused" | "done" | "cancelled";
export type PaymentStatus = "unpaid" | "partial" | "paid" | "refunded";

export const STATUS_LABELS: Record<WorkOrderStatus, string> = {
  new: "Новый",
  diagnostics: "Диагностика",
  awaiting_approval: "Согласование",
  in_progress: "В работе",
  awaiting_parts: "Ждёт запчасти",
  quality_check: "Проверка",
  ready: "Готов",
  closed: "Закрыт",
  cancelled: "Отменён",
};

/** Порядок колонок канбана и степпера (жизненный цикл). */
export const STATUS_ORDER: WorkOrderStatus[] = [
  "new",
  "diagnostics",
  "awaiting_approval",
  "in_progress",
  "awaiting_parts",
  "quality_check",
  "ready",
  "closed",
];

export const ORDER_DEPARTMENT_LABELS: Record<WorkOrderDepartment, string> = { service: "Сервис", detailing: "Детейлинг", mixed: "Смешанный" };
export const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  pending: "Ожидает",
  in_progress: "В работе",
  paused: "Пауза",
  done: "Готово",
  cancelled: "Отменена",
};
export const ITEM_STATUS_ICON: Record<ItemStatus, LucideIcon> = { pending: Circle, in_progress: CirclePlay, paused: CirclePause, done: CircleCheck, cancelled: CircleX };
export const PAYMENT_LABELS: Record<PaymentStatus, string> = { unpaid: "Не оплачен", partial: "Частично", paid: "Оплачен", refunded: "Возврат" };

export interface UserRef { id: string; full_name: string }
export interface ClientRef { id: string; full_name: string; phone: string }
export interface VehicleRef { id: string; make: string; model: string; plate_number: string | null }

export interface WorkOrderItem {
  id: string;
  service_id: string | null;
  name: string;
  department: Department;
  quantity: string;
  unit_price: string;
  discount_percent: string;
  total: string;
  norm_hours: string;
  norm_hours_total: string;
  mechanic: UserRef | null;
  status: ItemStatus;
  started_at: string | null;
  finished_at: string | null;
  actual_minutes: number;
  sort_order: number;
}

export interface WorkOrderPart {
  id: string;
  part_id: string | null;
  name: string;
  sku: string | null;
  unit: string | null;
  quantity: string;
  unit_price: string;
  total: string;
  unit_cost: string | null;
  in_stock: string | null;
  added_by: UserRef;
  created_at: string;
}

export interface WorkOrderListItem {
  id: string;
  number: string;
  location_id: string;
  status: WorkOrderStatus;
  department: WorkOrderDepartment;
  created_at: string;
  planned_ready_at: string | null;
  is_overdue: boolean;
  mileage_in: number | null;
  client: ClientRef;
  vehicle: VehicleRef;
  manager: UserRef;
  mechanics: UserRef[];
  items_count: number;
  items_done_count: number;
  works_total: string;
  parts_total: string;
  discount_total: string;
  total: string;
  paid_total: string;
  balance_due: string;
  payment_status: PaymentStatus;
  version: number;
}

export interface WorkOrder extends Omit<WorkOrderListItem, "client" | "vehicle"> {
  client: ClientRef & { discount_percent: number };
  vehicle: VehicleRef & { year: number | null; vin: string | null; color: string | null; mileage: number | null };
  complaint: string | null;
  intake_notes: string | null;
  diagnosis: string | null;
  discount_percent: string;
  started_at: string | null;
  ready_at: string | null;
  closed_at: string | null;
  cancel_reason: string | null;
  appointment_id: string | null;
  items: WorkOrderItem[];
  parts: WorkOrderPart[];
  allowed_transitions: WorkOrderStatus[];
  updated_at: string;
}

export interface StatusHistoryEntry {
  id: string;
  from_status: WorkOrderStatus | null;
  to_status: WorkOrderStatus;
  changed_by: UserRef;
  comment: string | null;
  created_at: string;
}

export interface WorkOrderComment {
  id: string;
  item_id: string | null;
  author: UserRef & { role: string };
  text: string;
  is_internal: boolean;
  created_at: string;
}

export interface OrderBoardColumn { status: WorkOrderStatus; total: number; items: WorkOrderListItem[] }
export interface OrderBoard { columns: OrderBoardColumn[] }
export interface OrderSummary { in_progress: number; awaiting_parts: number; ready: number; overdue: number; open_total: number }

/** Тело создания позиции работы (`NewItem`): каталожная или произвольная. */
export type NewItem =
  | { service_id: string; quantity?: string; discount_percent?: string; mechanic_id?: string | null; unit_price?: string }
  | { name: string; department: Department; unit_price: string; quantity?: string; discount_percent?: string; norm_hours?: string; mechanic_id?: string | null };

export type NewPart =
  | { part_id: string; quantity: string; unit_price?: string }
  | { name: string; quantity: string; unit_price: string };

export function isClosedOrder(s: WorkOrderStatus): boolean {
  return s === "closed" || s === "cancelled";
}

/** Разрешённые переходы (api-contract-m5, «Статусы»): нужны канбану, где карточки не несут `allowed_transitions`. */
export const TRANSITIONS: Record<WorkOrderStatus, WorkOrderStatus[]> = {
  new: ["diagnostics", "in_progress", "cancelled"],
  diagnostics: ["awaiting_approval", "in_progress", "cancelled"],
  awaiting_approval: ["in_progress", "diagnostics", "cancelled"],
  in_progress: ["awaiting_parts", "quality_check", "cancelled"],
  awaiting_parts: ["in_progress", "cancelled"],
  quality_check: ["in_progress", "ready", "cancelled"],
  ready: ["in_progress", "closed", "cancelled"],
  closed: [],
  cancelled: [],
};

/** Кнопка «Следующий статус»: основной шаг жизненного цикла. */
export const NEXT_STATUS: Partial<Record<WorkOrderStatus, WorkOrderStatus>> = {
  new: "in_progress",
  diagnostics: "in_progress",
  awaiting_approval: "in_progress",
  awaiting_parts: "in_progress",
  in_progress: "quality_check",
  quality_check: "ready",
  ready: "closed",
};
