/** Заглушка virtual:pwa-register для vitest (в тестах service worker не регистрируется). */
export function registerSW(): (reloadPage?: boolean) => Promise<void> {
  return async () => undefined;
}
