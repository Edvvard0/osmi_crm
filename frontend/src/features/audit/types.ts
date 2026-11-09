import type { Percent } from "./percent";

/* Модуль 11: журнал действий, сессии, системные настройки (api-contract-m11.md). */

export type AuditAction =
  | "create" | "update" | "delete" | "archive" | "restore" | "status_change" | "refund"
  | "login" | "login_failed" | "logout" | "token_reuse" | "password_change" | "export" | "revoke_session";

export interface AuditEntry {
  id: number;
  created_at: string;
  user: { id: string; full_name: string } | null;
  action: AuditAction | string;
  entity_type: string;
  entity_id: string | null;
  entity_label: string | null;
  entity_path: string | null;
  location: { id: string; name: string; timezone: string } | null;
  changes: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
}

export interface AuditMeta {
  actions: { value: string; label: string }[];
  entity_types: { value: string; label: string }[];
}

export interface HeatmapThresholds {
  hours: number[];
  actions: number[];
}

export interface SystemSettings {
  discount_alert_percent: Percent;
  daily_summary_time: string | null;
  session_retention_days: number;
  heatmap_thresholds: HeatmapThresholds;
  updated_at: string | null;
  updated_by: { id: string; full_name: string } | null;
}

export type SettingsPatch = Partial<Omit<SystemSettings, "updated_at" | "updated_by">>;

/** Активная сессия пользователя (в client.ts `Session` — это ответ входа, поэтому здесь UserSession). */
export interface UserSession {
  id: string;
  created_at: string;
  last_active_at: string;
  ip: string | null;
  user_agent: string | null;
  device: string;
  is_current: boolean;
}
