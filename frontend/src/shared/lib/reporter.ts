/** Отправка ошибок клиента на сервер (только лог). Сбой отправки молча игнорируется. */
let sent = 0;
const MAX_PER_SESSION = 10;

/** Убирает из текста всё, что похоже на персональные данные и секреты: email, телефоны, токены, строки запроса. */
export function scrub(v: string): string {
  return v
    .replace(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, "[email]")
    .replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, "[token]")
    .replace(/\bBearer\s+\S+/gi, "Bearer [token]")
    .replace(/\+?\d[\d\s().-]{8,}\d/g, "[number]")
    // Строка запроса и фрагмент в адресах (в том числе внутри стека) могут содержать поисковые фразы и имена.
    .replace(/\?[^\s)'"]*/g, "?")
    .replace(/#[^\s)'"]*/g, "");
}

function clip(v: unknown, n: number): string | undefined {
  if (typeof v !== "string" || !v) return undefined;
  // Сервер запрещает разметку в тексте — заменяем угловые скобки.
  return scrub(v).replace(/[<>]/g, "").slice(0, n);
}

/** Только путь без query и hash; идентификаторы заменены на :id. */
export function safePath(p: string): string {
  return p
    .split("?")[0]
    .split("#")[0]
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ":id")
    .replace(/\/\d+(?=\/|$)/g, "/:id");
}

/** Возвращает короткий код обращения (его видно на экране C-06 и в логе сервера) или undefined, если отправка не выполнялась. */
export function reportClientError(kind: string, err: unknown): string | undefined {
  if (sent >= MAX_PER_SESSION) return undefined;
  sent += 1;
  const code = Math.random().toString(36).slice(2, 8).toUpperCase();
  const e = err instanceof Error ? err : new Error(String(err));
  const body = {
    message: clip(e.message, 500) ?? "unknown",
    stack: clip(e.stack, 4000),
    url: clip(safePath(location.pathname), 500),
    kind: `${(clip(kind, 24) ?? "error").replace(/[^\w-]/g, "")}-${code}`,
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
  return code;
}

export function resetReporterForTests(): void {
  sent = 0;
}
