import clsx from "clsx";
import { type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Модальное окно: затемнение, Escape и клик по фону закрывают, фокус заперт внутри и возвращается на прежний элемент.
 * На телефоне занимает весь экран.
 */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = bodyRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? ref.current)?.focus();
    return () => prev?.focus?.();
  }, []);

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-stretch justify-center bg-black/50 sm:items-start sm:p-4 sm:pt-[6vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={clsx(
          "flex w-full flex-col overflow-hidden bg-surface text-fg shadow-lg sm:max-h-[88vh] sm:rounded-lg sm:border sm:border-border",
          wide ? "sm:max-w-2xl" : "sm:max-w-md",
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="truncate text-base font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Закрыть" className="rounded px-2 py-1 text-lg leading-none text-muted hover:text-fg">
            ×
          </button>
        </div>
        <div ref={bodyRef} className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
