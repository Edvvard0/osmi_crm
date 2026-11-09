import { useSyncExternalStore } from "react";

/**
 * Состояние соединения для баннера C-04 и блокировки мутаций.
 * Офлайн = браузер сообщает об отсутствии сети ИЛИ запрос завершился сетевой ошибкой / ответом из офлайн-кэша.
 * Сетевая ошибка снимается первым успешным ответом сервера (или проверкой после события `online`).
 */
export interface ConnectivityState {
  browserOnline: boolean;
  /** Был сбой сети (или ответ взят из кэша), успешного ответа сервера после него ещё не было. */
  netFailed: boolean;
  /** Время (мс) последнего успешного чтения для текущего экрана; null — данных нет. */
  dataAt: number | null;
}

const PROBE_URL = "/api/v1/health";
const PROBE_TIMEOUT_MS = 4000;
const RECOVERY_POLL_MS = 15_000;

let state: ConnectivityState = {
  browserOnline: typeof navigator === "undefined" ? true : navigator.onLine,
  netFailed: false,
  dataAt: null,
};
const listeners = new Set<() => void>();
const recoverListeners = new Set<() => void>();
/** Время данных по путям текущего экрана (из заголовка Date ответа: у ответа из кэша это время исходного ответа). */
let screenData = new Map<string, number>();
let lastDataAt: number | null = null;
let probing: Promise<void> | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;

function emit(next: Partial<ConnectivityState>): void {
  const merged = { ...state, ...next };
  if (merged.browserOnline === state.browserOnline && merged.netFailed === state.netFailed && merged.dataAt === state.dataAt) return;
  const was = isOffline(state);
  state = merged;
  listeners.forEach((l) => l());
  syncPolling();
  if (was && !isOffline(state)) recoverListeners.forEach((l) => l());
}

export const isOffline = (s: ConnectivityState = state): boolean => !s.browserOnline || s.netFailed;
export const getConnectivity = (): ConnectivityState => state;

function recomputeDataAt(): number | null {
  if (screenData.size) return Math.min(...screenData.values());
  return lastDataAt;
}

/** Сеть не отвечает: вызывается клиентом API при сетевой ошибке (не при HTTP-статусе и не при таймауте). */
export function reportNetworkError(): void {
  emit({ netFailed: true, dataAt: recomputeDataAt() });
}

/** Сервер ответил (любым HTTP-статусом) — сеть есть. */
export function reportReachable(): void {
  emit({ netFailed: false });
}

/** Успешное чтение: `date` — заголовок Date ответа, `fromCache` — ответ отдал service worker из кэша. */
export function reportData(path: string, dateHeader: string | null, fromCache: boolean): void {
  const parsed = dateHeader ? Date.parse(dateHeader) : NaN;
  const at = Number.isFinite(parsed) ? parsed : Date.now();
  screenData.set(path, at);
  if (!fromCache || lastDataAt === null) lastDataAt = Math.max(lastDataAt ?? 0, at);
  if (fromCache) emit({ netFailed: true, dataAt: recomputeDataAt() });
  else emit({ netFailed: false, dataAt: recomputeDataAt() });
}

/** Смена экрана: время «данных на HH:MM» считается заново по его запросам. */
export function resetScreenData(): void {
  screenData = new Map();
  emit({ dataAt: recomputeDataAt() });
}

/** Подписка на восстановление связи (например, чтобы перезапросить данные). */
export function onRecover(cb: () => void): () => void {
  recoverListeners.add(cb);
  return () => recoverListeners.delete(cb);
}

/** Проверка доступности сервера: любой HTTP-ответ означает, что сеть есть. */
export function probeConnection(): Promise<void> {
  if (probing) return probing;
  const p = (async () => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    try {
      await fetch(PROBE_URL, { method: "GET", cache: "no-store", signal: ctrl.signal });
      reportReachable();
    } catch {
      /* всё ещё нет связи */
    } finally {
      clearTimeout(timer);
    }
  })();
  probing = p;
  void p.finally(() => {
    if (probing === p) probing = null;
  });
  return p;
}

function syncPolling(): void {
  // Браузер считает, что сеть есть, но запросы падают: периодически проверяем, не восстановилась ли связь.
  const need = state.browserOnline && state.netFailed;
  if (need && !pollTimer) pollTimer = setInterval(() => void probeConnection(), RECOVERY_POLL_MS);
  if (!need && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    emit({ browserOnline: true });
    // Баннер исчезает после события online и первого успешного ответа: не ждём действий пользователя.
    if (state.netFailed) void probeConnection();
  });
  window.addEventListener("offline", () => emit({ browserOnline: false }));
}

/** Реактивное состояние для компонентов. */
export function useConnectivity(): ConnectivityState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    getConnectivity,
    getConnectivity,
  );
}

/** Только признак офлайна: компонентам-потребителям не нужны перерисовки при смене времени данных. */
export function useIsOffline(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => isOffline(),
    () => false,
  );
}

/** Сброс модуля между тестами. */
export function resetConnectivityForTests(): void {
  state = { browserOnline: typeof navigator === "undefined" ? true : navigator.onLine, netFailed: false, dataAt: null };
  screenData = new Map();
  lastDataAt = null;
  probing = null;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  listeners.forEach((l) => l());
}
