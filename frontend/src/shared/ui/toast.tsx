import { type ReactNode, createContext, useCallback, useContext, useMemo, useState } from "react";

import { toAppError } from "@/shared/api/errors";

type Kind = "info" | "success" | "error";
interface Toast { id: number; kind: Kind; text: string }
interface Ctx {
  push: (kind: Kind, text: string) => void;
  error: (e: unknown) => void;
}

const ToastCtx = createContext<Ctx | null>(null);
let seq = 0;

/** Глобальный вызов для кода вне React (обработчики window.onerror и т.п.) */
let external: Ctx | null = null;
export const toast = {
  error: (e: unknown) => external?.error(e),
  success: (t: string) => external?.push("success", t),
  /** Готовый безопасный текст (из словаря/констант) в виде сообщения об ошибке. */
  errorText: (t: string) => external?.push("error", t),
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Kind, text: string) => {
    const id = ++seq;
    setItems((x) => [...x.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 5000);
  }, []);
  // Показываем только безопасный текст из словаря.
  const error = useCallback((e: unknown) => push("error", toAppError(e).message), [push]);
  const value = useMemo(() => ({ push, error }), [push, error]);
  external = value;

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 md:bottom-6">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className="pointer-events-auto rounded-lg border border-border bg-surface px-4 py-2 text-sm shadow-lg"
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): Ctx {
  const c = useContext(ToastCtx);
  if (!c) throw new Error("ToastProvider missing");
  return c;
}
