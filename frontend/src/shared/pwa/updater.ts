import { useSyncExternalStore } from "react";

/**
 * C-05: состояние «доступна новая версия». Service worker регистрируется с registerType "prompt":
 * новая версия скачивается в фоне, перезагрузки без согласия пользователя нет.
 */
export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000;

interface UpdateState {
  needRefresh: boolean;
  /** «Позже»: скрыто до следующего запуска (хранится только в памяти). */
  dismissed: boolean;
}

let state: UpdateState = { needRefresh: false, dismissed: false };
const listeners = new Set<() => void>();
let applyFn: ((reload?: boolean) => Promise<void>) | null = null;

function set(next: Partial<UpdateState>): void {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export function setNeedRefresh(): void {
  set({ needRefresh: true, dismissed: false });
}
export function dismissUpdate(): void {
  set({ dismissed: true });
}
/** Активирует новую версию и перезагружает страницу (`updateServiceWorker(true)`). */
export async function applyUpdate(): Promise<void> {
  if (applyFn) await applyFn(true);
  else location.reload();
}

export function useUpdateState(): UpdateState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => state,
  );
}

/** Регистрация service worker и расписание проверок: при возврате вкладки в фокус и раз в 60 минут. */
export async function registerPwa(): Promise<void> {
  if (!import.meta.env.PROD || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  const { registerSW } = await import("virtual:pwa-register");
  applyFn = registerSW({
    onNeedRefresh: setNeedRefresh,
    onRegisteredSW(_url, reg) {
      if (!reg) return;
      let last = 0;
      const check = () => {
        // focus и visibilitychange приходят почти одновременно — одной проверки достаточно.
        if (!navigator.onLine || Date.now() - last < 30_000) return;
        last = Date.now();
        void reg.update().catch(() => undefined);
      };
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") check();
      });
      window.addEventListener("focus", check);
      setInterval(check, UPDATE_CHECK_INTERVAL_MS);
    },
  });
}

export function resetUpdateStateForTests(): void {
  state = { needRefresh: false, dismissed: false };
  applyFn = null;
  listeners.forEach((l) => l());
}
/** Только для тестов: подставить функцию применения обновления. */
export function setApplyForTests(fn: (reload?: boolean) => Promise<void>): void {
  applyFn = fn;
}
