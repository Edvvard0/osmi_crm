import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { CrmLocation } from "@/shared/api/types";

import type { LinkCode, NotificationSetting, TelegramStatus } from "./types";

const KEY = ["telegram", "status"] as const;
const SETTINGS_KEY = ["telegram", "settings"] as const;
export const POLL_MS = 3000;

/** Статус привязки; пока `poll` включён — опрос каждые 3 с (ожидание /start в боте). */
export function useTelegramStatus(poll: boolean) {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api<TelegramStatus>("/telegram/status"),
    meta: { silent: true },
    retry: false,
    refetchInterval: poll ? POLL_MS : false,
  });
}

export function useCreateLinkCode() {
  return useMutation({
    meta: { silent: true },
    mutationFn: () => api<LinkCode>("/telegram/link-code", { method: "POST", body: {} }),
  });
}

export function useUnlinkTelegram() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: () => api<void>("/telegram/link", { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY });
      qc.removeQueries({ queryKey: SETTINGS_KEY });
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
}

export function useNotificationSettings(enabled: boolean) {
  return useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: () => api<NotificationSetting[]>("/telegram/notification-settings"),
    meta: { silent: true },
    retry: false,
    enabled,
  });
}

/** Мгновенное сохранение переключателя: оптимистичное обновление и откат при ошибке. */
export function useToggleNotification() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { event_type: string; is_enabled: boolean }) =>
      api<NotificationSetting[]>("/telegram/notification-settings", { method: "PATCH", body: { items: [v] } }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: SETTINGS_KEY });
      const prev = qc.getQueryData<NotificationSetting[]>(SETTINGS_KEY);
      qc.setQueryData<NotificationSetting[]>(SETTINGS_KEY, (old) =>
        old?.map((s) => (s.event_type === v.event_type ? { ...s, is_enabled: v.is_enabled, is_default: false } : s)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(SETTINGS_KEY, ctx.prev);
    },
    onSuccess: (data) => qc.setQueryData(SETTINGS_KEY, data),
  });
}

/** D-06: ID группового чата точки (только директор). */
export function useSetLocationChat(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (telegram_chat_id: number | null) =>
      api<CrmLocation>(`/locations/${id}`, { method: "PATCH", body: { telegram_chat_id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["locations"] }),
  });
}

export function useLocationTelegramTest(id: string) {
  return useMutation({
    meta: { silent: true },
    mutationFn: () => api<{ sent: boolean }>(`/locations/${id}/telegram-test`, { method: "POST", body: {} }),
  });
}
