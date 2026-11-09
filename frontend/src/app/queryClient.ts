import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { AppError } from "@/shared/api/errors";
import { toast } from "@/shared/ui/toast";

function handle(e: unknown): void {
  // 401 обрабатывается клиентом API (refresh/выход), 422 показывается у полей формы.
  if (e instanceof AppError && (e.status === 401 || e.status === 422)) return;
  toast.error(e);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({ onError: handle }),
    // Мутации с meta.silent показывают ошибку в самой форме — повторный toast не нужен.
    mutationCache: new MutationCache({ onError: (e, _v, _c, m) => (m.meta?.silent ? undefined : handle(e)) }),
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        retry: (n, e) => !(e instanceof AppError && e.status >= 400 && e.status < 500) && n < 2,
      },
    },
  });
}
