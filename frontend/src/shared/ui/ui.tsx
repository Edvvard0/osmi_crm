import clsx from "clsx";
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  forwardRef,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Link, type LinkProps } from "react-router-dom";

import { useIsOffline } from "@/shared/lib/connectivity";

export const OFFLINE_HINT = "Нет соединения — действие недоступно";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: Variant;
    loading?: boolean;
    /** Кнопка не меняет данные (повтор чтения, переход): остаётся доступной офлайн. По умолчанию офлайн блокируются submit и danger. */
    offlineSafe?: boolean;
  }
>(function Button({ variant = "primary", loading, offlineSafe, className, children, disabled, title, ...rest }, ref) {
  const offline = useIsOffline();
  // Изменяющие действия офлайн недоступны (контракт модуля 12); сами запросы блокирует api-клиент.
  const blocked = offline && !offlineSafe && (rest.type === "submit" || variant === "danger");
  return (
    <button
      ref={ref}
      disabled={disabled || loading || blocked}
      aria-busy={loading || undefined}
      title={blocked ? OFFLINE_HINT : title}
      className={clsx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded px-4 text-sm font-medium transition-opacity disabled:opacity-50 md:min-h-10",
        variant === "primary" && "bg-accent text-accent-fg hover:opacity-90",
        variant === "secondary" && "border border-border bg-surface text-fg hover:bg-bg",
        variant === "ghost" && "text-fg hover:bg-border/50",
        variant === "danger" && "bg-danger text-white hover:opacity-90",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }>(
  function Input({ label, error, id, className, ...rest }, ref) {
    const inputId = id ?? `f-${label}`;
    return (
      <label htmlFor={inputId} className="block text-sm">
        <span className="mb-1 block text-muted">{label}</span>
        <input
          ref={ref}
          id={inputId}
          aria-invalid={!!error}
          aria-describedby={error ? `${inputId}-err` : undefined}
          className={clsx(
            "min-h-11 w-full rounded border bg-surface px-3 text-fg placeholder:text-muted md:min-h-10",
            error ? "border-danger" : "border-border",
            className,
          )}
          {...rest}
        />
        {error && (
          <span id={`${inputId}-err`} role="alert" className="mt-1 block text-xs text-danger">
            {error}
          </span>
        )}
      </label>
    );
  },
);

type Tone = "neutral" | "success" | "warning" | "danger";
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        tone === "neutral" && "border-border text-muted",
        tone === "success" && "border-success/40 text-success",
        tone === "warning" && "border-warning/40 text-warning",
        tone === "danger" && "border-danger/40 text-danger",
      )}
    >
      {children}
    </span>
  );
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  );
}
export const Th = ({ children }: { children?: ReactNode }) => (
  <th scope="col" className="border-b border-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted">
    {children}
  </th>
);
export const Td = ({ children }: { children?: ReactNode }) => <td className="border-b border-border px-3 py-2 last:border-0">{children}</td>;

export function Dialog({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  // Открываем через showModal(): верхний слой, затемнение, фокус внутри. Атрибут open в разметке
  // делал бы окно немодальным (обычным блоком поверх страницы). Без showModal (старые движки) — open.
  useLayoutEffect(() => {
    const d = ref.current;
    if (!open || !d || d.open) return;
    if (typeof d.showModal === "function") d.showModal();
    else d.setAttribute("open", "");
  }, [open]);
  if (!open) return null;
  // Портал в body: на окно не действуют стили родителя (space-y-* сбивает центрирование).
  return createPortal(
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="w-[min(92vw,28rem)] rounded-lg border border-border bg-surface p-5 text-fg backdrop:bg-black/50"
    >
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </dialog>,
    document.body,
  );
}

export function LinkButton({ variant = "primary", className, ...rest }: LinkProps & { variant?: "primary" | "secondary" }) {
  return (
    <Link
      className={clsx(
        "inline-flex min-h-11 items-center justify-center rounded px-4 text-sm font-medium md:min-h-10",
        variant === "primary" ? "bg-accent text-accent-fg hover:opacity-90" : "border border-border bg-surface text-fg hover:bg-bg",
        className,
      )}
      {...rest}
    />
  );
}

export function PasswordInput({ label, error, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input label={label} error={error} type={shown ? "text" : "password"} className="pr-24" {...rest} />
      <button
        type="button"
        onClick={() => setShown((v) => !v)}
        aria-pressed={shown}
        aria-label={shown ? "Скрыть пароль" : "Показать пароль"}
        className="absolute right-1 top-6 flex h-11 items-center rounded px-3 text-xs text-muted hover:text-fg md:h-10"
      >
        {shown ? "Скрыть" : "Показать"}
      </button>
    </div>
  );
}

export function Select({ label, error, children, className, id, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string }) {
  const selectId = id ?? `s-${label}`;
  return (
    <label htmlFor={selectId} className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      <select
        id={selectId}
        aria-invalid={!!error}
        className={clsx("min-h-11 w-full rounded border bg-surface px-3 text-fg md:min-h-10", error ? "border-danger" : "border-border", className)}
        {...rest}
      >
        {children}
      </select>
      {error && (
        <span role="alert" className="mt-1 block text-xs text-danger">
          {error}
        </span>
      )}
    </label>
  );
}

export function Checkbox({ label, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="flex min-h-11 items-center gap-2 text-sm md:min-h-10">
      <input type="checkbox" className="h-4 w-4" {...rest} />
      <span>{label}</span>
    </label>
  );
}

export function Alert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
      {children}
    </p>
  );
}

export function Loading() {
  return (
    <p role="status" className="py-8 text-center text-sm text-muted">
      Загрузка…
    </p>
  );
}

export function Textarea({ label, error, id, className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: string }) {
  const areaId = id ?? `t-${label}`;
  return (
    <label htmlFor={areaId} className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      <textarea
        id={areaId}
        rows={3}
        aria-invalid={!!error}
        className={clsx("w-full rounded border bg-surface px-3 py-2 text-fg", error ? "border-danger" : "border-border", className)}
        {...rest}
      />
      {error && (
        <span role="alert" className="mt-1 block text-xs text-danger">
          {error}
        </span>
      )}
    </label>
  );
}
