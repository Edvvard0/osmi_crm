import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { Page, Role, User } from "@/shared/api/types";

export const PAGE_SIZE = 50;

export interface UserFilters {
  search: string;
  role: "" | Role;
  location_id: string;
  is_active: "" | "true" | "false";
  offset: number;
}

export function useUsers(f: UserFilters) {
  const p = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(f.offset) });
  if (f.search) p.set("search", f.search);
  if (f.role) p.set("role", f.role);
  if (f.location_id) p.set("location_id", f.location_id);
  if (f.is_active) p.set("is_active", f.is_active);
  return useQuery({
    queryKey: ["users", p.toString()],
    queryFn: () => api<Page<User>>(`/users?${p.toString()}`),
    placeholderData: keepPreviousData,
  });
}

export function useUserById(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["users", "one", id],
    queryFn: () => api<User>(`/users/${id}`),
    enabled: enabled && !!id && id !== "new",
  });
}

export interface UserCreate {
  login: string;
  full_name: string;
  role: Role;
  password: string;
  location_ids: string[];
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: UserCreate) => api<User>("/users", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateUser(id: string, silent = true) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent },
    mutationFn: (b: Partial<Pick<User, "full_name" | "role" | "location_ids" | "is_active">>) =>
      api<User>(`/users/${id}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useResetPassword(id: string) {
  return useMutation({
    meta: { silent: true },
    mutationFn: (new_password: string) => api<void>(`/users/${id}/reset-password`, { body: { new_password } }),
  });
}
