import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { AppError } from "@/shared/api/errors";
import { isOffline } from "@/shared/lib/connectivity";
import { toast } from "@/shared/ui/toast";

/** Текст toast, если изменяющий запрос не дошёл до сервера (контракт модуля 12). */
export const MUTATION_NETWORK_ERROR_TEXT = "Нет соединения. Действие не выполнено";

function handle(e: unknown): void {
  // 401 обрабатывается клиентом API (refresh/выход), 422 показывается у полей формы.
  if (e instanceof AppError && (e.status === 401 || e.status === 422)) return;
  // Офлайн: чтения молча показывают баннер C-04, отдельные toast на каждый запрос не нужны.
  if (e instanceof AppError && e.code === "network_error" && isOffline()) return;
  toast.error(e);
}

function handleMutation(e: unknown): void {
  if (e instanceof AppError && e.code === "network_error") {
    toast.errorText(MUTATION_NETWORK_ERROR_TEXT);
    return;
  }
  handle(e);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    // Запросы с meta.silent показывают ошибку в самом блоке (например, карточка «Система») — toast не нужен.
    queryCache: new QueryCache({ onError: (e, q) => (q.meta?.silent ? undefined : handle(e)) }),
    // Мутации с meta.silent показывают ошибку в самой форме — повторный toast не нужен.
    mutationCache: new MutationCache({ onError: (e, _v, _c, m) => (m.meta?.silent ? undefined : handleMutation(e)) }),
    defaultOptions: {
      // Сетевой режим «always»: офлайн запросы всё равно уходят в сеть, где их перехватывает service worker
      // (ответ из кэша), а мутации не ставятся TanStack Query в очередь — блокировку делает api-клиент.
      mutations: { networkMode: "always", retry: false },
      queries: {
        networkMode: "always",
        staleTime: 15_000,
        retry: (n, e) => !(e instanceof AppError && e.status >= 400 && e.status < 500) && n < 2,
      },
    },
  });
}
