import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { Client, ClientDetail, ClientSource, ClientType, Page, Vehicle, VehicleDetail } from "@/shared/api/types";

export const CLIENTS_PAGE_SIZE = 50;

export interface ClientFilters {
  search: string;
  client_type: "" | ClientType;
  source: "" | ClientSource;
  archived: boolean;
  offset: number;
}

export function useClients(f: ClientFilters) {
  const p = new URLSearchParams({ limit: String(CLIENTS_PAGE_SIZE), offset: String(f.offset), archived: String(f.archived) });
  if (f.search) p.set("search", f.search);
  if (f.client_type) p.set("client_type", f.client_type);
  if (f.source) p.set("source", f.source);
  return useQuery({
    queryKey: ["clients", p.toString()],
    queryFn: () => api<Page<Client>>(`/clients?${p.toString()}`),
    placeholderData: keepPreviousData,
  });
}

export function useClientById(id: string | undefined) {
  return useQuery({
    queryKey: ["client", id],
    queryFn: () => api<ClientDetail>(`/clients/${encodeURIComponent(id ?? "")}`),
    enabled: !!id && id !== "new",
  });
}

export interface ClientInput {
  client_type: ClientType;
  full_name: string;
  company_name: string | null;
  inn: string | null;
  phone: string;
  phone_extra: string | null;
  email: string | null;
  source: ClientSource | null;
  discount_percent: number;
  notes: string | null;
}

export function useCreateClient() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: ClientInput) => api<Client>("/clients", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });
}

function useInvalidateClient() {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ["clients"] }), qc.invalidateQueries({ queryKey: ["client"] }), qc.invalidateQueries({ queryKey: ["vehicle"] })]);
}

export function useUpdateClient(id: string) {
  const inv = useInvalidateClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: Partial<ClientInput>) => api<Client>(`/clients/${encodeURIComponent(id)}`, { method: "PATCH", body: b }),
    onSuccess: inv,
  });
}

export function useArchiveClient(id: string) {
  const inv = useInvalidateClient();
  return useMutation({
    mutationFn: (archive: boolean) => api<Client>(`/clients/${encodeURIComponent(id)}/${archive ? "archive" : "restore"}`, { method: "POST", body: {} }),
    onSuccess: inv,
  });
}

export function useVehicleById(id: string | undefined) {
  return useQuery({
    queryKey: ["vehicle", id],
    queryFn: () => api<VehicleDetail>(`/vehicles/${encodeURIComponent(id ?? "")}`),
    enabled: !!id,
  });
}

export interface VehicleInput {
  make: string;
  model: string;
  year: number | null;
  vin: string | null;
  plate_number: string | null;
  color: string | null;
  mileage: number | null;
  notes: string | null;
}

export function useCreateVehicle(clientId: string) {
  const inv = useInvalidateClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: VehicleInput) => api<Vehicle>(`/clients/${encodeURIComponent(clientId)}/vehicles`, { body: b }),
    onSuccess: inv,
  });
}

export function useUpdateVehicle(id: string) {
  const inv = useInvalidateClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: Partial<VehicleInput>) => api<Vehicle>(`/vehicles/${encodeURIComponent(id)}`, { method: "PATCH", body: b }),
    onSuccess: inv,
  });
}

export function useArchiveVehicle(id: string) {
  const inv = useInvalidateClient();
  return useMutation({
    mutationFn: (archive: boolean) => api<Vehicle>(`/vehicles/${encodeURIComponent(id)}/${archive ? "archive" : "restore"}`, { method: "POST", body: {} }),
    onSuccess: inv,
  });
}
