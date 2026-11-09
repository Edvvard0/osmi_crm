import clsx from "clsx";
import { X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useState } from "react";

import { useDebounced } from "@/pages/catalog/common";
import { type AppError, toAppError } from "@/shared/api/errors";
import type { Part } from "@/shared/api/types";
import { formatMoney } from "@/shared/lib/money";
import { Button, Input, Loading } from "@/shared/ui/ui";

import { findPartByBarcode, useSearchParts } from "./api";
import { fmtQty, incQty, lineTotal, parseDecimalOrNull, parseQty, stockErrorText, unitLabel } from "./format";

export type PartLite = Pick<Part, "id" | "sku" | "name" | "unit"> & Partial<Pick<Part, "barcode" | "brand" | "is_active">>;

export interface Line {
  part: PartLite;
  qty: string;
  cost: string;
}

/** Поиск запчасти по артикулу/названию/штрихкоду; Enter — точное совпадение по штрихкоду (ввод сканера). */
export function PartPicker({ onPick, label = "Добавить позицию" }: { onPick: (p: PartLite) => void; label?: string }) {
  const [text, setText] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const search = useDebounced(text.trim(), 250);
  const q = useSearchParts(search);
  const results = (q.data?.items ?? []).filter((p) => p.is_active);

  function pick(p: PartLite) {
    onPick(p);
    setText("");
    setHint(null);
  }

  async function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const code = text.trim();
    if (!code) return;
    try {
      const exact = await findPartByBarcode(code);
      if (exact) return pick(exact);
    } catch {
      /* ошибка сети: покажем подсказку ниже */
    }
    if (results.length === 1 && search === code) return pick(results[0]);
    setHint("Позиция с таким штрихкодом не найдена");
  }

  return (
    <div className="relative">
      <Input
        id="stock-part-picker"
        label={label}
        type="search"
        autoComplete="off"
        placeholder="Артикул, название или штрихкод (Enter)"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setHint(null);
        }}
        onKeyDown={(e) => void onKeyDown(e)}
      />
      {hint && <p role="status" className="mt-1 text-xs text-danger">{hint}</p>}
      {search && text.trim() && (
        <ul className="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded border border-border bg-surface shadow-lg" aria-label="Результаты поиска">
          {q.isLoading && <li className="px-3 py-2"><Loading /></li>}
          {q.data && results.length === 0 && <li className="px-3 py-2 text-sm text-muted">Ничего не найдено</li>}
          {results.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => pick(p)} className="flex w-full flex-col px-3 py-2 text-left text-sm hover:bg-bg">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-muted">{p.sku}{p.brand ? ` · ${p.brand}` : ""}{p.barcode ? ` · ${p.barcode}` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Добавление позиции в список: повтор той же позиции увеличивает количество. */
export function addLine(lines: Line[], p: PartLite): Line[] {
  const i = lines.findIndex((l) => l.part.id === p.id);
  if (i < 0) return [...lines, { part: p, qty: "1", cost: "" }];
  return lines.map((l, k) => (k === i ? { ...l, qty: incQty(l.qty) } : l));
}

/** Таблица строк «позиция — количество [— цена закупки — сумма]». */
export function LinesEditor({
  lines,
  setLines,
  withCost,
  error,
  badPartId,
  invalid,
}: {
  lines: Line[];
  setLines: (l: Line[]) => void;
  withCost?: boolean;
  /** Ошибка по полю items или нехватка остатка. */
  error?: AppError | null;
  badPartId?: string;
  /** Подсветка строк с невалидным вводом после попытки отправки. */
  invalid?: boolean;
}) {
  const set = (i: number, patch: Partial<Line>) => setLines(lines.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  const stockText = error ? stockErrorText(error, (id) => lines.find((l) => l.part.id === id)?.part.name) : null;
  if (lines.length === 0) return <p className="rounded border border-dashed border-border py-6 text-center text-sm text-muted">Добавьте позиции через поиск выше</p>;
  return (
    <ul className="space-y-2" aria-label="Позиции">
      {lines.map((l, i) => {
        const qty = parseQty(l.qty);
        const cost = withCost ? parseDecimalOrNull(l.cost) : "0.00";
        const rowBad = (l.part.id === (badPartId ?? error?.details.part_id) && !!error && error.code === "insufficient_stock") || (!!invalid && (qty === null || cost === null));
        return (
          <li key={l.part.id} className={clsx("rounded border p-2", rowBad ? "border-danger" : "border-border")}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{l.part.name}</div>
                <div className="text-xs text-muted">{l.part.sku} · {unitLabel(l.part.unit)}</div>
              </div>
              <Button type="button" variant="ghost" aria-label={`Убрать ${l.part.name}`} onClick={() => setLines(lines.filter((_, k) => k !== i))}>
                <X size={16} aria-hidden="true" />
              </Button>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Input
                id={`qty-${l.part.id}`}
                label={`Количество (${unitLabel(l.part.unit)})`}
                inputMode="decimal"
                value={l.qty}
                onChange={(e) => set(i, { qty: e.target.value })}
                error={invalid && qty === null ? "Число больше 0, до 3 знаков" : undefined}
              />
              {withCost && (
                <Input
                  id={`cost-${l.part.id}`}
                  label="Цена закупки, ₽"
                  inputMode="decimal"
                  value={l.cost}
                  onChange={(e) => set(i, { cost: e.target.value })}
                  error={invalid && cost === null ? "Число не меньше 0" : undefined}
                />
              )}
              {withCost && (
                <div className="text-sm">
                  <span className="mb-1 block text-muted">Сумма</span>
                  <span className="flex min-h-10 items-center whitespace-nowrap font-medium">
                    {qty && cost ? formatMoney(lineTotal(qty, cost)) : "—"}
                  </span>
                </div>
              )}
            </div>
            {rowBad && l.part.id === (badPartId ?? error?.details.part_id) && stockText && <p role="alert" className="mt-1 text-xs text-danger">{stockText}</p>}
          </li>
        );
      })}
    </ul>
  );
}

/** Сообщение об ошибке формы операции: нехватка остатка собирается из details; поля показываются отдельно. */
export function OpError({ err, lines }: { err: unknown; lines: Line[] }) {
  if (!err) return null;
  const e = toAppError(err);
  if (e.code === "validation_error") return null;
  const text = stockErrorText(e, (id) => lines.find((l) => l.part.id === id)?.part.name) ?? e.message;
  return <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{text}</p>;
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "danger" }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className={clsx("text-lg font-semibold", tone === "danger" && "text-danger")}>{value}</div>
    </div>
  );
}

export const QtyText = ({ v }: { v: string }) => <span className="whitespace-nowrap">{fmtQty(v)}</span>;
