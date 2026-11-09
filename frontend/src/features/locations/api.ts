import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { CrmLocation } from "@/shared/api/types";

import { useAuth } from "@/features/auth/AuthProvider";

export function useLocations() {
  return useQuery({ queryKey: ["locations"], queryFn: () => api<CrmLocation[]>("/locations") });
}

export function useLocationById(id: string | undefined) {
  return useQuery({
    queryKey: ["locations", id],
    queryFn: () => api<CrmLocation>(`/locations/${id}`),
    enabled: !!id && id !== "new",
  });
}

export interface LocationInput {
  name: string;
  address: string;
  phone?: string | null;
  is_active?: boolean;
  timezone?: string;
  work_start?: string;
  work_end?: string;
}

export function useCreateLocation() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: LocationInput) => api<CrmLocation>("/locations", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["locations"] }),
  });
}

export function useUpdateLocation(id: string, silent = true) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent },
    mutationFn: (b: Partial<LocationInput>) => api<CrmLocation>(`/locations/${id}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["locations"] }),
  });
}

/** Переключатель точки в шапке: руководитель выбирает «Все точки» или конкретную, остальные — из своих. */
export function useActiveLocation() {
  const { user, locationId, setLocationId } = useAuth();
  const q = useLocations();
  const items = (q.data ?? []).filter((l) => l.is_active || user?.role === "director");
  const isDirector = user?.role === "director";
  const valid = locationId === "all" ? isDirector : items.some((l) => l.id === locationId);
  const value = valid ? locationId : isDirector ? "all" : (items[0]?.id ?? "");
  const current = items.find((l) => l.id === value) ?? null;
  return { items, value, current, set: setLocationId, isDirector, loading: q.isLoading };
}
