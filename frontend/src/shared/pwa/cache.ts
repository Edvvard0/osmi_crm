import { API_CACHE_NAME } from "@/shared/lib/apiCachePolicy";
import { readPref, writePref } from "@/shared/lib/storage";

const OWNER_KEY = "crm.cache-owner";

/** Удаляет runtime-кэш чтений API (`api-read-v1`). Без Cache API (тесты, старые браузеры) — тихо ничего не делает. */
export async function clearApiReadCache(): Promise<void> {
  try {
    if (typeof caches === "undefined") return;
    await caches.delete(API_CACHE_NAME);
  } catch {
    /* кэша нет или он недоступен — чистить нечего */
  }
}

/**
 * Ключ кэша — полный URL, поэтому ответы одного пользователя нельзя отдавать другому.
 * Вызывается ДО первого запроса после входа: если на этом устройстве раньше работал другой пользователь
 * (выход не был выполнен, например истёк refresh-cookie), кэш удаляется.
 */
export async function ensureCacheOwner(userId: string): Promise<void> {
  if (readPref(OWNER_KEY) !== userId) await clearApiReadCache();
  writePref(OWNER_KEY, userId);
}

/** Выход (logout или принудительный): кэш удаляется, владелец сбрасывается. */
export async function clearCacheOnLogout(): Promise<void> {
  writePref(OWNER_KEY, "");
  await clearApiReadCache();
}
