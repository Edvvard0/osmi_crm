import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { useActiveLocation } from "@/features/locations/api";
import { api } from "@/shared/api/client";
import type { Page, Part } from "@/shared/api/types";

import type {
  InventoryLine,
  QtyLine,
  ReceiptLine,
  StockBalance,
  StockMovement,
  StockMovementType,
  StockPage,
  StockScope,
  StockSort,
} from "./types";

export const STOCK_PAGE_SIZE = 50;
const enc = encodeURIComponent;

function qs(o: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Точка склада: значение в URL `?location_id=`, иначе активная точка шапки, иначе первая доступная. */
export function useStockLocation() {
  const [sp, setSp] = useSearchParams();
  const { items, current, loading, isDirector } = useActiveLocation();
  const fromUrl = sp.get("location_id") ?? "";
  const valid = items.some((l) => l.id === fromUrl);
  const locationId = valid ? fromUrl : (current?.id ?? items[0]?.id ?? "");
  const setLocationId = (id: string) =>
    setSp((p) => {
      const n = new URLSearchParams(p);
      n.set("location_id", id);
      return n;
    });
  return { locationId, setLocationId, items, loading, isDirector };
}

/* ---------- Остатки ---------- */

export interface StockFilters {
  location_id: string;
  search?: string;
  scope?: StockScope;
  sort?: StockSort;
  order?: "asc" | "desc";
}

export function useStock(f: StockFilters, offset: number) {
  const q = qs({ ...f, limit: STOCK_PAGE_SIZE, offset });
  return useQuery({
    queryKey: ["stock", "list", q],
    queryFn: () => api<StockPage>(`/stock${q}`),
    placeholderData: keepPreviousData,
    enabled: !!f.location_id,
  });
}

/** Все остатки «на складе» постранично по 200 (для инвентаризации). */
export async function loadAllStocked(locationId: string): Promise<StockBalance[]> {
  const items: StockBalance[] = [];
  for (let offset = 0, i = 0; i < 50; i++, offset += 200) {
    const p = await api<StockPage>(`/stock${qs({ location_id: locationId, scope: "stocked", sort: "name", limit: 200, offset })}`);
    items.push(...p.items);
    if (offset + 200 >= p.total || p.items.length === 0) break;
  }
  return items;
}

export function useStockItem(partId: string, locationId: string) {
  return useQuery({
    queryKey: ["stock", "item", partId, locationId],
    queryFn: () => api<StockBalance>(`/stock/${enc(partId)}${qs({ location_id: locationId })}`),
    enabled: !!partId && !!locationId,
  });
}

export function useSetMinQuantity(partId: string, locationId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (min_quantity: string) =>
      api<StockBalance>(`/stock/${enc(partId)}${qs({ location_id: locationId })}`, { method: "PATCH", body: { min_quantity } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stock"] }),
  });
}

/* ---------- Движения ---------- */

export interface MovementFilters {
  location_id: string;
  part_id?: string;
  movement_type?: StockMovementType | "";
  date_from?: string;
  date_to?: string;
}

export function useMovements(f: MovementFilters, offset: number) {
  const q = qs({ ...f, limit: STOCK_PAGE_SIZE, offset });
  return useQuery({
    queryKey: ["stock", "movements", q],
    queryFn: () => api<Page<StockMovement>>(`/stock/movements${q}`),
    placeholderData: keepPreviousData,
    enabled: !!f.location_id,
  });
}

/* ---------- Операции ---------- */

function useStockMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stock"] }),
  });
}

export interface ReceiptInput { location_id: string; supplier?: string; document_number?: string; items: ReceiptLine[] }
export const useReceipt = () => useStockMutation((b: ReceiptInput) => api<{ movements: StockMovement[] }>("/stock/receipts", { body: b }));

export interface WriteOffInput { location_id: string; reason: string; items: QtyLine[] }
export const useWriteOff = () => useStockMutation((b: WriteOffInput) => api<{ movements: StockMovement[] }>("/stock/write-offs", { body: b }));

export interface TransferInput { from_location_id: string; to_location_id: string; comment?: string; items: QtyLine[] }
export const useTransfer = () =>
  useStockMutation((b: TransferInput) => api<{ out: StockMovement[]; in: StockMovement[] }>("/stock/transfers", { body: b }));

export interface InventoryInput { location_id: string; comment?: string; items: InventoryLine[] }
export const useInventoryCommit = () =>
  useStockMutation((b: InventoryInput) => api<{ movements: StockMovement[]; skipped: number }>("/stock/inventory/commit", { body: b }));

export const useReverse = (id: string) =>
  useStockMutation((b: { reason: string }) => api<StockMovement>(`/stock/movements/${enc(id)}/reverse`, { body: b }));

/* ---------- Поиск запчастей справочника ---------- */

/** Запчасти справочника (для прихода). Пустой запрос — пустой список. */
export function useSearchParts(search: string) {
  return useQuery({
    queryKey: ["catalog", "parts", "stock-search", search],
    queryFn: () => api<Page<Part>>(`/parts${qs({ search, limit: 10 })}`),
    enabled: search.length > 0,
  });
}

/** Точное совпадение по штрихкоду (ввод сканера). */
export async function findPartByBarcode(code: string): Promise<Part | null> {
  const p = await api<Page<Part>>(`/parts${qs({ search: code, limit: 20 })}`);
  return p.items.find((x) => x.barcode === code && x.is_active) ?? null;
}
