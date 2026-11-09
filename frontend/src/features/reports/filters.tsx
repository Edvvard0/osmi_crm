import clsx from "clsx";
import { useState } from "react";

import { toAppError } from "@/shared/api/errors";
import { Button, Input } from "@/shared/ui/ui";

import { PERIOD_LABELS, type PeriodKind, periodRange, reportErrorText, useToday } from "./lib";

export interface PeriodState {
  kind: PeriodKind;
  from: string;
  to: string;
  today: string;
  setKind: (k: PeriodKind) => void;
  setFrom: (v: string) => void;
  setTo: (v: string) => void;
  /** Задать произвольный период целиком (переход из других экранов). */
  setRange: (from: string, to: string) => void;
}

/** Период с пресетами «сегодня / неделя / месяц» и произвольным интервалом. Даты — в поясе выбранной точки. */
export function usePeriod(initial: PeriodKind = "month", initialRange?: { from: string; to: string }): PeriodState {
  const today = useToday();
  const [kind, setKindState] = useState<PeriodKind>(initialRange ? "custom" : initial);
  const [custom, setCustom] = useState<{ from: string; to: string } | null>(initialRange ?? null);
  const range = kind === "custom" ? (custom ?? periodRange("month", today)) : periodRange(kind, today);
  return {
    kind,
    from: range.from,
    to: range.to,
    today,
    setKind: (k) => {
      if (k === "custom" && !custom) setCustom(periodRange("month", today));
      setKindState(k);
    },
    setFrom: (v) => setCustom({ from: v, to: range.to }),
    setTo: (v) => setCustom({ from: range.from, to: v }),
    setRange: (from, to) => {
      setCustom({ from, to });
      setKindState("custom");
    },
  };
}

const KINDS: PeriodKind[] = ["today", "week", "month", "custom"];

export function PeriodFilter({ period, idPrefix = "p" }: { period: PeriodState; idPrefix?: string }) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div role="group" aria-label="Период" className="inline-flex overflow-hidden rounded border border-border">
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={period.kind === k}
            onClick={() => period.setKind(k)}
            className={clsx(
              "min-h-10 border-r border-border px-3 text-sm last:border-r-0",
              period.kind === k ? "bg-accent text-accent-fg" : "bg-surface text-fg hover:bg-bg",
            )}
          >
            {PERIOD_LABELS[k]}
          </button>
        ))}
      </div>
      {period.kind === "custom" && (
        <>
          <div className="w-40">
            <Input id={`${idPrefix}-from`} label="Начало периода" type="date" value={period.from} max={period.to || undefined} onChange={(e) => period.setFrom(e.target.value)} />
          </div>
          <div className="w-40">
            <Input id={`${idPrefix}-to`} label="Конец периода" type="date" value={period.to} min={period.from || undefined} onChange={(e) => period.setTo(e.target.value)} />
          </div>
        </>
      )}
    </div>
  );
}

/** Баннер ошибки запроса с «Повторить»: ошибки полей периода объяснены, внутренних деталей нет. */
export function QueryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const e = toAppError(error);
  return (
    <div role="alert" className="rounded-lg border border-border bg-surface p-4 text-sm">
      <p className="font-medium">Не удалось загрузить</p>
      <p className="mt-1 text-muted">
        {reportErrorText(error)}
        {e.requestId ? ` · Код обращения: ${e.requestId}` : ""}
      </p>
      <Button className="mt-3" variant="secondary" onClick={onRetry}>
        Повторить
      </Button>
    </div>
  );
}

export function EmptyNote({ children }: { children: string }) {
  return <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">{children}</p>;
}
