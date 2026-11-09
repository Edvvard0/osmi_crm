import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { Page, User } from "@/shared/api/types";

import type { AuditEntry, AuditMeta, SettingsPatch, SystemSettings, UserSession } from "./types";

export const AUDIT_PAGE = 50;
const MAX_OFFSET = 10_000;

export interface AuditFilters {
  date_from: string;
  date_to: string;
  user_id: string;
  action: string;
  entity_type: string;
  location_id: string;
}

export function useAuditMeta() {
  return useQuery({ queryKey: ["audit-meta"], queryFn: () => api<AuditMeta>("/audit-log/meta"), staleTime: 5 * 60_000 });
}

export function useAuditLog(f: AuditFilters) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) p.set(k, v);
  p.set("limit", String(AUDIT_PAGE));
  const qs = p.toString();
  return useInfiniteQuery({
    queryKey: ["audit", qs],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<Page<AuditEntry>>(`/audit-log?${qs}&offset=${pageParam}`),
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((n, pg) => n + pg.items.length, 0);
      return last.items.length > 0 && loaded < last.total && loaded <= MAX_OFFSET ? loaded : undefined;
    },
  });
}

export function useUserOptions() {
  return useQuery({
    queryKey: ["users", "audit-options"],
    queryFn: () => api<Page<User>>("/users?limit=100"),
    staleTime: 60_000,
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["system-settings"], queryFn: () => api<SystemSettings>("/settings") });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: SettingsPatch) => api<SystemSettings>("/settings", { method: "PATCH", body: b }),
    onSuccess: (data) => qc.setQueryData(["system-settings"], data),
  });
}

export function useSessions() {
  return useQuery({ queryKey: ["auth-sessions"], queryFn: () => api<UserSession[]>("/auth/sessions") });
}

export function useRevokeSession() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (id: string) => api<void>(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["auth-sessions"] }),
  });
}

export function useRevokeOthers() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: () => api<void>("/auth/sessions/revoke-others", { method: "POST", body: undefined }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["auth-sessions"] }),
  });
}

export function useRevokeUserSessions(userId: string) {
  return useMutation({
    meta: { silent: true },
    mutationFn: () => api<void>(`/users/${userId}/revoke-sessions`, { method: "POST" }),
  });
}
