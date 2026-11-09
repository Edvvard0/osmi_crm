/** Отправка ошибок клиента на сервер (только лог). Сбой отправки молча игнорируется. */
let sent = 0;
const MAX_PER_SESSION = 10;

function clip(v: unknown, n: number): string | undefined {
  if (typeof v !== "string" || !v) return undefined;
  // Сервер запрещает разметку в тексте — заменяем угловые скобки.
  return v.replace(/[<>]/g, "").slice(0, n);
}

export function reportClientError(kind: string, err: unknown): void {
  if (sent >= MAX_PER_SESSION) return;
  sent += 1;
  const e = err instanceof Error ? err : new Error(String(err));
  const body = {
    message: clip(e.message, 500) ?? "unknown",
    stack: clip(e.stack, 4000),
    url: clip(location.pathname, 500),
    kind: clip(kind, 32),
  };
  try {
    void fetch("/api/v1/client-errors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* ignore */
  }
}

export function resetReporterForTests(): void {
  sent = 0;
}
