import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { toAppError } from "@/shared/api/errors";
import { Alert, Badge, Button, Dialog } from "@/shared/ui/ui";

import { useCreateLinkCode, useNotificationSettings, useTelegramStatus, useToggleNotification, useUnlinkTelegram } from "./api";
import type { LinkCode } from "./types";

function fmtLeft(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** C-02, секция «Telegram»: привязка аккаунта и уведомления роли. */
export function TelegramSection() {
  const qc = useQueryClient();
  const [code, setCode] = useState<LinkCode | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [confirm, setConfirm] = useState(false);

  const expiresMs = code ? Date.parse(code.expires_at) : 0;
  const waiting = !!code && now < expiresMs;
  const status = useTelegramStatus(waiting);
  const gen = useCreateLinkCode();
  const unlink = useUnlinkTelegram();

  // Обратный отсчёт; секундный таймер работает только пока код активен.
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [waiting]);

  const linked = status.data?.linked ?? false;
  useEffect(() => {
    if (linked && code) setCode(null);
  }, [linked, code]);

  function requestCode() {
    gen.mutate(undefined, {
      onSuccess: (c) => {
        setNow(Date.now());
        setCode(c);
      },
      onError: () => void qc.invalidateQueries({ queryKey: ["telegram", "status"] }),
    });
  }

  const genErr = gen.error ? toAppError(gen.error) : null;
  const unlinkErr = unlink.error ? toAppError(unlink.error) : null;

  return (
    <section aria-labelledby="s-tg" className="space-y-3">
      <h2 id="s-tg" className="text-base font-semibold">Telegram</h2>
      {status.isLoading && <div role="status" aria-label="Загрузка Telegram" className="h-16 animate-pulse rounded bg-border/50" />}
      {status.isError && <p className="text-sm text-muted">Состояние Telegram недоступно</p>}
      {status.data && !status.data.enabled && <p className="text-sm text-muted">Telegram не настроен, обратитесь к руководителю</p>}

      {status.data?.enabled && !linked && (
        <div className="space-y-3">
          {!waiting && (
            <>
              <p className="text-sm text-muted">Привяжите Telegram, чтобы получать рабочие уведомления.</p>
              <Button onClick={requestCode} loading={gen.isPending}>
                {code ? "Получить новый код" : "Привязать Telegram"}
              </Button>
              {code && <p className="text-sm text-muted">Срок действия кода истёк.</p>}
            </>
          )}
          {waiting && code && (
            <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
              <div>
                <div className="text-xs text-muted">Код привязки</div>
                <div data-testid="tg-code" className="mt-1 font-mono text-3xl font-semibold tracking-widest">{code.code}</div>
              </div>
              <p className="text-sm text-muted">
                Откройте бота и нажмите «Запустить» или отправьте ему <span className="font-mono">/start {code.code}</span>. Код действует ещё{" "}
                <span aria-label="Осталось времени">{fmtLeft(expiresMs - now)}</span>.
              </p>
              <a
                href={code.link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-10 items-center justify-center rounded bg-accent px-4 text-sm font-medium text-accent-fg hover:opacity-90"
              >
                Открыть в Telegram
              </a>
            </div>
          )}
          {genErr && <Alert>{genErr.message}</Alert>}
        </div>
      )}

      {status.data?.enabled && linked && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm">
              <Badge tone="success">Подключён</Badge>
              <span>{status.data.telegram_username ? `@${status.data.telegram_username}` : "Telegram"}</span>
            </div>
            <Button variant="secondary" onClick={() => setConfirm(true)}>Отключить</Button>
          </div>
          {unlinkErr && <Alert>{unlinkErr.message}</Alert>}
          <NotificationList />
        </div>
      )}

      <Dialog open={confirm} title="Отключить Telegram?" onClose={() => setConfirm(false)}>
        <p className="mb-4 text-sm text-muted">Уведомления перестанут приходить, неотправленные сообщения будут отменены.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(false)}>Отмена</Button>
          <Button variant="danger" loading={unlink.isPending} onClick={() => unlink.mutate(undefined, { onSettled: () => setConfirm(false) })}>
            Подтвердить отключение
          </Button>
        </div>
      </Dialog>
    </section>
  );
}

function NotificationList() {
  const q = useNotificationSettings(true);
  const toggle = useToggleNotification();
  const err = toggle.error ? toAppError(toggle.error) : null;
  if (q.isLoading) return <div role="status" aria-label="Загрузка уведомлений" className="h-24 animate-pulse rounded bg-border/50" />;
  if (q.isError) return <Alert>{toAppError(q.error).message}</Alert>;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Уведомления</h3>
      <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
        {(q.data ?? []).map((s) => (
          <li key={s.event_type}>
            <label className="flex min-h-12 cursor-pointer items-center justify-between gap-3 px-3 py-2">
              <span className="min-w-0 text-sm">
                <span className="block">{s.title}</span>
                {s.description && <span className="block text-xs text-muted">{s.description}</span>}
              </span>
              <input
                type="checkbox"
                role="switch"
                aria-label={s.title}
                className="h-5 w-5 shrink-0"
                checked={s.is_enabled}
                onChange={(e) => toggle.mutate({ event_type: s.event_type, is_enabled: e.target.checked })}
              />
            </label>
          </li>
        ))}
      </ul>
      {err && <Alert>{err.message}</Alert>}
    </div>
  );
}
