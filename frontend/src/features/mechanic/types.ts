import type { Department } from "@/shared/api/types";
import type { ItemStatus, UserRef, VehicleRef, WorkOrderStatus } from "@/features/orders/types";

/* Модуль 6: рабочее место механика (api-contract-m6.md). Цен и контактов клиента в этих типах нет. */

export interface TaskVehicle { id: string; make: string; model: string; year: number | null; plate_number: string | null; color: string | null }

export interface MechanicTask {
  item_id: string;
  order_id: string;
  order_number: string;
  order_status: WorkOrderStatus;
  department: Department;
  name: string;
  quantity: string;
  norm_hours: string;
  status: ItemStatus;
  worked_seconds: number;
  running_since: string | null;
  vehicle: TaskVehicle;
  planned_ready_at: string | null;
  is_overdue: boolean;
  can_start: boolean;
  finished_at: string | null;
}

export interface TaskItemBrief {
  item_id: string;
  name: string;
  quantity: string;
  norm_hours: string;
  status: ItemStatus;
  worked_seconds: number;
  running_since: string | null;
}

export interface MechanicComment { id: string; item_id: string | null; author: UserRef; text: string; created_at: string }

export interface MechanicTaskDetail extends MechanicTask {
  complaint: string | null;
  intake_notes: string | null;
  mileage_in: number | null;
  my_items: TaskItemBrief[];
  comments: MechanicComment[];
  server_time: string;
}

export type TaskScope = "today" | "open";
export interface TaskList { active: MechanicTask | null; items: MechanicTask[]; server_time: string }
export interface TimerResult { task: MechanicTask; active: MechanicTask | null; server_time: string }
export interface FinishResult extends TimerResult { order_status: WorkOrderStatus; order_auto_moved: boolean }

export type PartRequestStatus = "new" | "approved" | "rejected" | "issued";
export const PART_REQUEST_LABELS: Record<PartRequestStatus, string> = { new: "Новая", approved: "Одобрена", rejected: "Отклонена", issued: "Выдана" };

export interface PartRef { id: string; name: string; sku: string }
export interface MechanicPartRequest {
  id: string;
  order_id: string;
  order_number: string;
  item_id: string | null;
  item_name: string | null;
  part: PartRef | null;
  description: string;
  quantity: string;
  unit: string | null;
  status: PartRequestStatus;
  reject_reason: string | null;
  created_at: string;
  handled_at: string | null;
}

export interface PartRequestFull {
  id: string;
  location_id: string;
  order: { id: string; number: string; status: WorkOrderStatus; version: number };
  vehicle: VehicleRef;
  item_id: string | null;
  item_name: string | null;
  mechanic: UserRef;
  part: (PartRef & { unit: string | null; sale_price: string; in_stock: string | null }) | null;
  description: string;
  quantity: string;
  status: PartRequestStatus;
  reject_reason: string | null;
  handled_by: UserRef | null;
  handled_at: string | null;
  created_at: string;
}

export interface PartHit { id: string; sku: string; name: string; brand: string | null; unit: string }

export type Priority = "low" | "medium" | "high";
export const PRIORITY_LABELS: Record<Priority, string> = { low: "Низкий", medium: "Средний", high: "Высокий" };
export type RecommendationStatus = "open" | "done" | "declined";

export interface VehicleRecommendation {
  id: string;
  vehicle_id: string;
  work_order_id: string | null;
  work_order_number: string | null;
  text: string;
  priority: Priority;
  status: RecommendationStatus;
  created_by: UserRef;
  created_at: string;
  updated_at: string;
}
