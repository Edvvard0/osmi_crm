import { type ReactNode, useEffect, useState } from "react";

import { type AppError, messageFor } from "@/shared/api/errors";
import { Alert, Badge, Button, Table, Td, Th } from "@/shared/ui/ui";

export function useDebounced(value: string, ms = 300): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function ActiveBadge({ active }: { active: boolean }) {
  return <Badge tone={active ? "success" : "neutral"}>{active ? "Активна" : "Неактивна"}</Badge>;
}

/** 409 unique_violation → понятное сообщение из словаря (по ключу конкретного поля). */
export function uniqueMessage(err: AppError | null, key: string): string | undefined {
  return err && err.status === 409 && err.code === "unique_violation" ? messageFor(key) : undefined;
}

/** Общая ошибка формы: не показываем то, что уже выведено у полей. */
export function FormError({ err }: { err: AppError | null }) {
  if (!err || err.code === "validation_error" || err.code === "unique_violation") return null;
  return <Alert>{err.message}</Alert>;
}

export function FormActions({ pending, onCancel, submitLabel = "Сохранить" }: { pending: boolean; onCancel: () => void; submitLabel?: string }) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button type="button" variant="secondary" onClick={onCancel}>Отмена</Button>
      <Button type="submit" loading={pending}>{submitLabel}</Button>
    </div>
  );
}

/** Desktop — таблица, mobile — список карточек. */
export function ResponsiveList<T>({
  items,
  head,
  row,
  card,
  id,
}: {
  items: T[];
  head: string[];
  row: (t: T) => ReactNode[];
  card: (t: T) => ReactNode;
  id: (t: T) => string;
}) {
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <thead>
            <tr>{head.map((h, i) => <Th key={i}>{h}</Th>)}</tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={id(t)}>{row(t).map((c, i) => <Td key={i}>{c}</Td>)}</tr>
            ))}
          </tbody>
        </Table>
      </div>
      <ul className="space-y-2 md:hidden">
        {items.map((t) => (
          <li key={id(t)} className="rounded-lg border border-border bg-surface p-3">{card(t)}</li>
        ))}
      </ul>
    </>
  );
}

export function Pager({ offset, size, total, onChange }: { offset: number; size: number; total: number; onChange: (o: number) => void }) {
  if (total <= size) return null;
  return (
    <div className="flex items-center justify-between text-sm text-muted">
      <span>{offset + 1}–{Math.min(offset + size, total)} из {total}</span>
      <div className="flex gap-2">
        <Button variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>Назад</Button>
        <Button variant="secondary" disabled={offset + size >= total} onClick={() => onChange(offset + size)}>Далее</Button>
      </div>
    </div>
  );
}
