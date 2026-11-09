/**
 * Политика офлайн-кэша ответов API (контракт модуля 12, «Что кэшируется»).
 * Единственный источник правды: из этого файла строится и регулярное выражение для service worker
 * (vite.config.ts), и проверка в тестах. Файл не должен импортировать ничего из приложения.
 *
 * Кэшируется ТОЛЬКО то, что явно перечислено в белом списке; чёрный список — страховка от ошибки в нём.
 */

export const API_CACHE_NAME = "api-read-v1";
export const API_CACHE_TIMEOUT_SECONDS = 4;
export const API_CACHE_MAX_ENTRIES = 100;
export const API_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60;
/** Заголовок, который service worker добавляет к ответу, взятому из кэша (сеть недоступна или ответила дольше 4 с). */
export const FROM_CACHE_HEADER = "X-From-Cache";

const ID = "[^/?#]+";

/** Список и карточка (один сегмент id) — вложенные ресурсы (платежи, печать, история) не кэшируются. */
const listAndCard = (name: string) => `${name}(?:/${ID})?`;

const WHITELIST = [
  listAndCard("work-orders"),
  "mechanic(?:/[^?#]*)?",
  listAndCard("appointments"),
  listAndCard("services"),
  listAndCard("service-categories"),
  listAndCard("posts"),
  listAndCard("locations"),
  listAndCard("parts"),
];

/** Префиксы, которые не кэшируются никогда (финансы, персональные данные, администрирование). */
const BLACKLIST = [
  "auth", "users", "clients", "vehicles", "search", "telegram", "payments", "expenses", "cash", "stock",
  "payroll", "reports", "me", "audit-log", "settings", "health", "system",
];

const PREFIX = "/api/v1/";

/** Часть выражения после схемы и хоста: `/api/v1/(…)` + необязательная строка запроса. */
export const API_CACHE_PATH_SOURCE = String.raw`/api/v1/(?:${WHITELIST.join("|")})(?:\?[^#]*)?(?:#.*)?$`;

/** Регулярное выражение для workbox: сопоставляется с полным URL запроса. */
export function apiCacheUrlPattern(): RegExp {
  return new RegExp(String.raw`^https?://[^/]+${API_CACHE_PATH_SOURCE}`);
}

/** Путь (с query или без) можно класть в кэш: метод GET проверяется отдельно, статус — тоже. */
export function isApiCacheablePath(pathWithQuery: string): boolean {
  if (!pathWithQuery.startsWith(PREFIX)) return false;
  const rest = pathWithQuery.slice(PREFIX.length);
  const first = rest.split(/[/?#]/, 1)[0];
  if (BLACKLIST.includes(first)) return false;
  return new RegExp(`^${API_CACHE_PATH_SOURCE}`).test(pathWithQuery);
}

/** Запрос можно кэшировать целиком (метод + путь). */
export function isApiCacheableRequest(method: string, pathWithQuery: string): boolean {
  return method.toUpperCase() === "GET" && isApiCacheablePath(pathWithQuery);
}
