import type { PartDepartment, PartUnit } from "@/shared/api/types";

export interface PartBrief {
  id: string;
  sku: string;
  name: string;
  brand: string | null;
  barcode: string | null;
  unit: PartUnit;
  department: PartDepartment;
  sale_price: string;
  is_active: boolean;
}

export interface StockBalance {
  location_id: string;
  part: PartBrief;
  quantity: string;
  min_quantity: string;
  avg_cost: string;
  stock_value: string;
  is_low: boolean;
  updated_at: string | null;
}

export interface StockTotals {
  positions: number;
  low_count: number;
  stock_value: string;
}

export interface StockPage {
  items: StockBalance[];
  total: number;
  totals: StockTotals;
}

export type StockMovementType =
  | "receipt"
  | "issue_to_order"
  | "return_from_order"
  | "write_off"
  | "transfer_out"
  | "transfer_in"
  | "adjustment";

export const MOVEMENT_LABELS: Record<StockMovementType, string> = {
  receipt: "Приход",
  issue_to_order: "Выдача в заказ",
  return_from_order: "Возврат из заказа",
  write_off: "Списание",
  transfer_out: "Перемещение (расход)",
  transfer_in: "Перемещение (приход)",
  adjustment: "Корректировка",
};

export interface StockMovement {
  id: string;
  location_id: string;
  part: { id: string; sku: string; name: string; unit: PartUnit };
  movement_type: StockMovementType;
  quantity: string;
  unit_cost: string;
  total: string;
  balance_after: string;
  work_order: { id: string; number: string } | null;
  related_movement_id: string | null;
  reversed: boolean;
  supplier: string | null;
  document_number: string | null;
  reason: string | null;
  created_by: { id: string; full_name: string };
  created_at: string;
}

export type StockSort = "name" | "sku" | "quantity" | "stock_value";
export type StockScope = "stocked" | "low" | "all";

export interface ReceiptLine { part_id: string; quantity: string; unit_cost: string }
export interface QtyLine { part_id: string; quantity: string }
export interface InventoryLine { part_id: string; expected_quantity: string; actual_quantity: string }
