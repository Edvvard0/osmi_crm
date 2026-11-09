import { useState } from "react";

import { type AppError, toAppError } from "@/shared/api/errors";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Dialog } from "@/shared/ui/ui";

import { useRevokeOthers, useRevokeSession, useSessions } from "./api";
import type { UserSession } from "./types";

function fmt(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

/** C-02 «Безопасность»: активные сессии текущего пользователя. */
export function SessionsSection() {
  const toast = useToast();
  const q = useSessions();
  const revoke = useRevokeSession();
  const revokeOthers = useRevokeOthers();
  const [target, setTarget] = useState<UserSession | null>(null);
  const [allOpen, setAllOpen] = useState(false);

  const items = q.data ?? [];
  const others = items.filter((s) => !s.is_current);
  const actionErr: AppError | null = revoke.error ? toAppError(revoke.error) : revokeOthers.error ? toAppError(revokeOthers.error) : null;

  return (
    <section aria-labelledby="s-sessions" className="space-y-3">
      <h2 id="s-sessions" className="text-base font-semibold">Активные сессии</h2>
      {q.isLoading ? (
        <p role="status" className="text-sm text-muted">Загрузка…</p>
      ) : q.isError ? (
        <div className="space-y-2">
          <Alert>{toAppError(q.error).message}</Alert>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      ) : (
        <>
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
            {items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 font-medium" title={s.user_agent ?? undefined}>
                    {s.device}
                    {s.is_current && <Badge tone="success">Это устройство</Badge>}
                  </p>
                  <p className="text-xs text-muted">
                    IP: {s.ip ?? "—"} · Активность: {fmt(s.last_active_at)}
                  </p>
                </div>
                {!s.is_current && (
                  <Button variant="secondary" onClick={() => setTarget(s)}>Завершить</Button>
                )}
              </li>
            ))}
          </ul>
          {others.length === 0 ? (
            <p className="text-sm text-muted">Других активных сессий нет</p>
          ) : (
            <Button variant="secondary" onClick={() => setAllOpen(true)}>Завершить все остальные</Button>
          )}
        </>
      )}
      {actionErr && <Alert>{actionErr.message}</Alert>}

      <Dialog open={!!target} title="Завершить сессию?" onClose={() => setTarget(null)}>
        <p className="text-sm text-muted">Устройство «{target?.device}» будет разлогинено.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setTarget(null)}>Отмена</Button>
          <Button
            variant="danger"
            loading={revoke.isPending}
            onClick={() => target && revoke.mutate(target.id, { onSuccess: () => { setTarget(null); toast.push("success", "Сессия завершена"); }, onError: () => setTarget(null) })}
          >
            Завершить
          </Button>
        </div>
      </Dialog>
      <Dialog open={allOpen} title="Завершить все остальные сессии?" onClose={() => setAllOpen(false)}>
        <p className="text-sm text-muted">Все устройства, кроме этого, будут разлогинены.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setAllOpen(false)}>Отмена</Button>
          <Button
            variant="danger"
            loading={revokeOthers.isPending}
            onClick={() => revokeOthers.mutate(undefined, { onSuccess: () => { setAllOpen(false); toast.push("success", "Остальные сессии завершены"); }, onError: () => setAllOpen(false) })}
          >
            Завершить
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
