import { FROM_CACHE_HEADER } from "@/shared/lib/apiCachePolicy";
import { getConnectivity, isOffline, probeConnection, reportData, reportNetworkError, reportReachable } from "@/shared/lib/connectivity";

import { AppError, codeForStatus } from "./errors";
import type { Session } from "./types";

const BASE = "/api/v1";
const TIMEOUT_MS = 15_000;

let accessToken: string | null = null;
let refreshing: Promise<Session | null> | null = null;
let onAuthLost: (() => void) | null = null;

export function setAccessToken(t: string | null): void {
  accessToken = t;
}
export function setAuthLostHandler(fn: (() => void) | null): void {
  onAuthLost = fn;
}

/** Один параллельный refresh: все 401 ждут один и тот же запрос (ротация токена не должна срабатывать дважды). */
export function refreshSession(): Promise<Session | null> {
  if (refreshing) return refreshing;
  const p = (async () => {
    try {
      const r = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" });
      reportReachable();
      if (!r.ok) return null;
      const data = (await r.json()) as Partial<Session>;
      if (typeof data.access_token !== "string" || !data.access_token) return null;
      accessToken = data.access_token;
      return data as Session;
    } catch {
      reportNetworkError();
      return null;
    }
  })();
  refreshing = p;
  void p.finally(() => {
    if (refreshing === p) refreshing = null;
  });
  return p;
}

async function parseError(res: Response): Promise<AppError> {
  let code = codeForStatus(res.status);
  let fields: Record<string, string> = {};
  let requestId: string | undefined;
  const details: Record<string, string> = {};
  try {
    const body = (await res.json()) as {
      error?: { code?: string; fields?: Record<string, string>; request_id?: string; details?: Record<string, unknown> };
    };
    // Берём только код и имена полей; message сервера намеренно игнорируется.
    if (typeof body.error?.code === "string") code = body.error.code;
    if (body.error?.fields && typeof body.error.fields === "object") fields = body.error.fields;
    if (body.error?.details && typeof body.error.details === "object") {
      for (const [k, v] of Object.entries(body.error.details)) if (typeof v === "string") details[k] = v;
    }
    requestId = typeof body.error?.request_id === "string" ? body.error.request_id : undefined;
  } catch {
    /* тело не JSON — остаёмся на коде по статусу */
  }
  const ra = Number(res.headers.get("Retry-After"));
  return new AppError(code, res.status, fields, requestId, Number.isFinite(ra) && ra > 0 ? ra : undefined, details);
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  skipAuthRetry?: boolean;
  /** Ответ — бинарное тело (PDF): возвращается Blob, а не JSON. */
  blob?: boolean;
  /** Изменяющий запрос, который нужно отправить даже без сети (выход из системы). */
  allowOffline?: boolean;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = (opts.method ?? (opts.body ? "POST" : "GET")).toUpperCase();
  const isRead = method === "GET";
  // Мутации офлайн заблокированы централизованно: очереди отложенных действий нет.
  if (!isRead && !opts.allowOffline) {
    const c = getConnectivity();
    // Браузер считает, что сеть есть, но недавний запрос упал — проверяем связь перед отправкой.
    if (c.browserOnline && c.netFailed) await probeConnection();
    if (isOffline()) throw new AppError("offline");
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  opts.signal?.addEventListener("abort", () => ctrl.abort());
  const usedToken = accessToken;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      credentials: "include",
      signal: ctrl.signal,
      headers: {
        ...(opts.body ? { "Content-Type": "application/json" } : {}),
        ...(usedToken ? { Authorization: `Bearer ${usedToken}` } : {}),
      },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw new AppError("timeout");
    reportNetworkError();
    throw new AppError("network_error");
  } finally {
    clearTimeout(timer);
  }

  // Любой HTTP-ответ — сервер достижим. Ответ из офлайн-кэша service worker помечен заголовком.
  const fromCache = res.headers.get(FROM_CACHE_HEADER) === "1";
  if (isRead && res.ok) reportData(path, res.headers.get("Date"), fromCache);
  else if (!fromCache) reportReachable();

  if (res.status === 401 && !opts.skipAuthRetry && path !== "/auth/login" && path !== "/auth/refresh") {
    if (accessToken !== usedToken) {
      // Токен уже обновил параллельный запрос — просто повторяем с новым.
      if (accessToken) return api<T>(path, { ...opts, skipAuthRetry: true });
    } else if (await refreshSession()) {
      return api<T>(path, { ...opts, skipAuthRetry: true });
    } else {
      accessToken = null;
      onAuthLost?.();
    }
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  if (opts.blob) return (await res.blob()) as T;
  try {
    return (await res.json()) as T;
  } catch {
    throw new AppError("unknown", res.status);
  }
}
