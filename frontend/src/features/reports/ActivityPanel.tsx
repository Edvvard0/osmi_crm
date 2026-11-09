import { useState } from "react";
import { Link } from "react-router-dom";

import { LoadError, Skeleton } from "@/features/orders/ui";
import { Select } from "@/shared/ui/ui";

import { ActivityHeatmap, type HeatmapVariant } from "./ActivityHeatmap";
import { useActivityDetails, useActivityHeatmap } from "./api";
import { enc, formatDateLong, formatDuration, formatTime, monthOf, shiftMonth, useToday } from "./lib";
import type { ActionEntry, HoursEntry } from "./types";

export type RangeKey = "3m" | "12m" | `y${number}`;

export function rangeDates(key: RangeKey, today: string): { from: string; to: string } {
  if (key === "3m") return { from: `${shiftMonth(monthOf(today), -2)}-01`, to: today };
  if (key === "12m") return { from: `${shiftMonth(monthOf(today), -11)}-01`, to: today };
  const y = key.slice(1);
  const end = `${y}-12-31`;
  return { from: `${y}-01-01`, to: end < today ? end : today };
}

/** Список записей за выбранный день (работы механика либо действия менеджера/директора). */
export function ActivityDayList({ userId, date, tz }: { userId: string; date: string | null; tz: string }) {
  const q = useActivityDetails(userId, date ?? "", date ?? "", !!date);
  if (!date) return <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Выберите день на карте</p>;
  if (q.isLoading) return <Skeleton lines={3} />;
  if (q.error) return <LoadError error={q.error} onRetry={() => void q.refetch()} />;
  const day = q.data?.days.find((d) => d.date === date) ?? null;

  return (
    <section aria-label="Записи за день" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold">{formatDateLong(date)}</h3>
        {day && q.data?.kind === "hours" && day.total_minutes !== null && <p className="text-sm text-muted">Всего: {formatDuration(day.total_minutes)}</p>}
        {day && q.data?.kind === "actions" && day.actions !== null && <p className="text-sm text-muted">Действий: {day.actions}</p>}
      </div>
      {!day || day.entries.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Нет активности</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
          {q.data?.kind === "hours"
            ? (day.entries as HoursEntry[]).map((e, i) => (
                <li key={`${e.item_id}-${e.started_at}-${i}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <div className="min-w-0">
                    <p className="break-words font-medium">{e.item_name}</p>
                    <p className="break-words text-muted">
                      <Link to={`/orders/${enc(e.order.id)}`} className="underline underline-offset-2">Заказ {e.order.number}</Link>
                      {e.plate_number ? ` · ${e.plate_number}` : ""}
                    </p>
                  </div>
                  <p className="whitespace-nowrap text-muted">
                    {formatTime(e.started_at, tz)}–{e.ended_at ? formatTime(e.ended_at, tz) : "…"} · {formatDuration(e.minutes)}
                  </p>
                </li>
              ))
            : (day.entries as ActionEntry[]).map((e, i) => (
                <li key={`${e.at}-${i}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <p className="min-w-0 break-words">{e.label}</p>
                  <p className="whitespace-nowrap text-muted">{formatTime(e.at, tz)}</p>
                </li>
              ))}
        </ul>
      )}
      {day?.truncated && <p className="text-xs text-muted">Показаны первые 200 записей дня</p>}
    </section>
  );
}

/** Карта + итоги + список выбранного дня. Используется в D-05, MG-17 и M-07. */
export function ActivityPanel({
  userId,
  defaultRange,
  variant,
  showDayList = true,
}: {
  userId: string;
  defaultRange: "3m" | "12m";
  variant?: HeatmapVariant;
  showDayList?: boolean;
}) {
  const today = useToday();
  const [range, setRange] = useState<RangeKey>(defaultRange);
  const [selected, setSelected] = useState<string | null>(null);
  const { from, to } = rangeDates(range, today);
  const meta = useActivityHeatmap(userId, from, to);
  const tz = meta.data?.timezone ?? "Europe/Moscow";
  const year = Number(today.slice(0, 4));
  const day = selected ?? to;

  return (
    <div className="space-y-4">
      <div className="max-w-xs">
        <Select label="Период карты" value={range} onChange={(e) => { setRange(e.target.value as RangeKey); setSelected(null); }}>
          <option value="3m">Последние 3 месяца</option>
          <option value="12m">Последние 12 месяцев</option>
          {[year, year - 1, year - 2].map((y) => (
            <option key={y} value={`y${y}`}>{y} год</option>
          ))}
        </Select>
      </div>
      <ActivityHeatmap userId={userId} from={from} to={to} variant={variant} selected={selected} onSelect={setSelected} />
      {showDayList && <ActivityDayList userId={userId} date={day} tz={tz} />}
    </div>
  );
}
