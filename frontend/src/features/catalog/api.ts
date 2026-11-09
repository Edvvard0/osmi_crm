import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { Category, Department, Page, Part, PartDepartment, PartUnit, Post, PostType, Service, ServicePrice, ServiceUnit } from "@/shared/api/types";

export const PAGE_SIZE = 50;
const ALL_LIMIT = 200;

function qs(o: object): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o) as [string, string | number | boolean | undefined | null][]) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/* ---------- Категории ---------- */

export function useCategories(f: { department?: Department | ""; is_active?: boolean } = {}) {
  const q = qs({ department: f.department, is_active: f.is_active });
  return useQuery({ queryKey: ["catalog", "categories", q], queryFn: () => api<Category[]>(`/service-categories${q}`) });
}

export interface CategoryCreate { name: string; department: Department; sort_order?: number }

export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: CategoryCreate) => api<Category>("/service-categories", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog"] }),
  });
}

export function useUpdateCategory(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: Partial<Pick<Category, "name" | "sort_order" | "is_active">>) =>
      api<Category>(`/service-categories/${id}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog"] }),
  });
}

/* ---------- Услуги ---------- */

export interface ServiceFilters {
  search?: string;
  category_id?: string;
  department?: Department | "";
  is_active?: boolean;
  /** Менеджер обязан передавать точку; руководитель — только если нужна цена точки. */
  location_id?: string;
}

export function useServices(f: ServiceFilters, offset: number, enabled = true) {
  const q = qs({ ...f, limit: PAGE_SIZE, offset });
  return useQuery({
    queryKey: ["catalog", "services", q],
    queryFn: () => api<Page<Service>>(`/services${q}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Все услуги постранично по 200 (для счётчиков дерева и матрицы цен). */
export function useAllServices(f: ServiceFilters, enabled = true) {
  return useQuery({
    queryKey: ["catalog", "services-all", qs(f)],
    enabled,
    queryFn: async () => {
      const items: Service[] = [];
      for (let offset = 0, i = 0; i < 50; i++, offset += ALL_LIMIT) {
        const p = await api<Page<Service>>(`/services${qs({ ...f, limit: ALL_LIMIT, offset })}`);
        items.push(...p.items);
        if (offset + ALL_LIMIT >= p.total || p.items.length === 0) break;
      }
      return items;
    },
  });
}

export interface ServiceInput {
  name: string;
  description: string | null;
  unit: ServiceUnit;
  base_price: string;
  norm_hours: string | null;
  duration_minutes: number;
}

export function useCreateService() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: ServiceInput & { category_id: string; code: string }) => api<Service>("/services", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog"] }),
  });
}

export function useUpdateService(id: string, silent = true) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent },
    mutationFn: (b: Partial<ServiceInput & { is_active: boolean }>) => api<Service>(`/services/${id}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog"] }),
  });
}

/* ---------- Цены по точкам ---------- */

/** Переопределения цен по каждой точке: один запрос на точку. */
export function usePricesByLocation(locationIds: string[]) {
  const results = useQueries({
    queries: locationIds.map((id) => ({
      queryKey: ["catalog", "prices", id],
      queryFn: () => api<ServicePrice[]>(`/service-prices?location_id=${encodeURIComponent(id)}`),
    })),
  });
  const map = new Map<string, string>();
  locationIds.forEach((lid, i) => results[i]?.data?.forEach((p) => map.set(`${p.service_id}:${lid}`, p.price)));
  return { map, loading: results.some((r) => r.isLoading), error: results.find((r) => r.error)?.error ?? null };
}

export function useSetPrice() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { serviceId: string; locationId: string; price: string }) =>
      api<ServicePrice>(`/services/${v.serviceId}/prices/${v.locationId}`, { method: "PUT", body: { price: v.price } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog"] }),
  });
}

export function useResetPrice() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { serviceId: string; locationId: string }) =>
      api<void>(`/services/${v.serviceId}/prices/${v.locationId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog"] }),
  });
}

/* ---------- Посты ---------- */

export function usePosts(locationId: string) {
  return useQuery({
    queryKey: ["catalog", "posts", locationId],
    queryFn: () => api<Post[]>(`/locations/${locationId}/posts`),
    enabled: !!locationId,
  });
}

export interface PostInput { name: string; post_type: PostType; department: Department; sort_order?: number }

export function useCreatePost(locationId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: PostInput) => api<Post>(`/locations/${locationId}/posts`, { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog", "posts"] }),
  });
}

export function useUpdatePost(id: string, silent = true) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent },
    mutationFn: (b: Partial<PostInput & { is_active: boolean }>) => api<Post>(`/posts/${id}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog", "posts"] }),
  });
}

/* ---------- Запчасти ---------- */

export function useParts(f: { search?: string; department?: PartDepartment | "" }, offset: number) {
  const q = qs({ ...f, limit: PAGE_SIZE, offset });
  return useQuery({
    queryKey: ["catalog", "parts", q],
    queryFn: () => api<Page<Part>>(`/parts${q}`),
    placeholderData: keepPreviousData,
  });
}

export interface PartInput {
  name: string;
  brand: string | null;
  barcode: string | null;
  unit: PartUnit;
  department: PartDepartment;
  sale_price: string;
}

export function useCreatePart() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: PartInput & { sku: string }) => api<Part>("/parts", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog", "parts"] }),
  });
}

export function useUpdatePart(id: string, silent = true) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent },
    mutationFn: (b: Partial<PartInput & { is_active: boolean }>) => api<Part>(`/parts/${id}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["catalog", "parts"] }),
  });
}
