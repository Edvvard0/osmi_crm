import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api/client";

import type { SystemStatus } from "./types";

/** Состояние системы для карточки D-01. Ошибка показывается в самой карточке, а не тостом (meta.silent). */
export function useSystemStatus() {
  return useQuery({
    queryKey: ["system", "status"],
    queryFn: () => api<SystemStatus>("/system/status"),
    refetchInterval: 60_000,
    retry: false,
    meta: { silent: true },
  });
}
