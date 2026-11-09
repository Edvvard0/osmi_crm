import { Badge } from "@/shared/ui/ui";

import { useSystemStatus } from "./api";
import type { SystemStatus } from "./types";

const OUTBOX_STALE_SECONDS = 15 * 60;
const BACKUP_STALE_HOURS = 36;

type Tone = "neutral" | "success" | "warning" | "danger";

function fmt(iso: string | null, tz: string): string {
  if (!iso) return "нет данных";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "нет данных";
  try {
    return new Intl.DateTimeFormat("ru-RU", { timeZone: tz, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(d);
  } catch {
    return d.toLocaleString("ru-RU");
  }
}

function outboxTone(s: SystemStatus): { tone: Tone; text: string } {
  const { pending, failed_24h, oldest_pending_age_seconds } = s.outbox;
  const text = `в очереди ${pending}, ошибок за сутки ${failed_24h}`;
  if (failed_24h > 0 || (oldest_pending_age_seconds ?? 0) > OUTBOX_STALE_SECONDS) return { tone: failed_24h > 0 ? "danger" : "warning", text };
  return { tone: "success", text };
}

function backupTone(s: SystemStatus): Tone {
  if (!s.last_backup_at) return "warning";
  const hours = (Date.parse(s.server_time) - Date.parse(s.last_backup_at)) / 3_600_000;
  return hours > BACKUP_STALE_HOURS ? "warning" : "success";
}

function Row({ label, tone, children }: { label: string; tone: Tone; children: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="flex items-center gap-2 text-right">
        <span>{children}</span>
        <Badge tone={tone}>{tone === "success" ? "ОК" : tone === "danger" ? "Ошибка" : tone === "warning" ? "Внимание" : "—"}</Badge>
      </dd>
    </div>
  );
}

/** D-01: карточка «Система» (только для руководителя). */
export function SystemCard() {
  const q = useSystemStatus();
  const s = q.data;
  return (
    <section aria-labelledby="system-card-title" className="mt-6 max-w-xl rounded-lg border border-border bg-surface p-4">
      <h2 id="system-card-title" className="text-base font-semibold">Система</h2>
      {q.isPending && (
        <div role="status" aria-label="Загрузка состояния системы" className="mt-3 animate-pulse space-y-2">
          <div className="h-5 rounded bg-border" />
          <div className="h-5 rounded bg-border" />
          <div className="h-5 rounded bg-border" />
        </div>
      )}
      {q.isError && <p role="alert" className="mt-3 text-sm text-muted">Нет данных о состоянии системы</p>}
      {s && (
        <dl className="mt-2 divide-y divide-border">
          <Row label="Воркер" tone={s.worker.ok ? "success" : "danger"}>
            {s.worker.ok ? `работает (${fmt(s.worker.last_heartbeat_at, s.app_timezone)})` : `не отвечает (${fmt(s.worker.last_heartbeat_at, s.app_timezone)})`}
          </Row>
          <Row label="Очередь уведомлений" tone={outboxTone(s).tone}>{outboxTone(s).text}</Row>
          <Row label="Резервная копия" tone={backupTone(s)}>{fmt(s.last_backup_at, s.app_timezone)}</Row>
        </dl>
      )}
    </section>
  );
}
