/** Ответ GET /system/status (только director), см. docs/api-contract-m12.md. */
export interface SystemStatus {
  server_time: string;
  app_timezone: string;
  env: "prod" | "dev" | "test";
  migrations: { current: string | null; head: string | null };
  worker: { last_heartbeat_at: string | null; ok: boolean };
  outbox: { pending: number; failed_24h: number; oldest_pending_age_seconds: number | null };
  telegram: { mode: "disabled" | "polling" | "webhook"; bot_username: string | null };
  last_backup_at: string | null;
  version: string;
}
