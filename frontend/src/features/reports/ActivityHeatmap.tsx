import clsx from "clsx";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { addDays, weekStart } from "@/features/appointments/time";
import { LoadError } from "@/features/orders/ui";
import { formatHours } from "@/shared/lib/money";
import { Button, Table, Td, Th } from "@/shared/ui/ui";

import { useActivityHeatmap } from "./api";
import { formatDateLong, formatDuration, formatQty, monthShort, plural } from "./lib";
import type { ActivityDay, ActivityHeatmapData, ActivityKind, ActivityLevel } from "./types";

export type HeatmapVariant = "desktop" | "mobile";

const GAP = 3;
const SIZE: Record<HeatmapVariant, number> = { desktop: 12, mobile: 16 };
const MONTH_ROW = 14;

const LEVEL_CLASS: Record<ActivityLevel, string> = {
  0: "bg-border/50",
  1: "bg-accent/20",
  2: "bg-accent/40",
  3: "bg-accent/65",
  4: "bg-accent",
};

const WEEKDAY_LABELS = ["Пн", "", "Ср", "", "Пт", "", ""];

/** Телефон — 16 px и 3 месяца по умолчанию, остальное — 12 px. Без matchMedia (тесты) — desktop. */
export function useHeatmapVariant(): HeatmapVariant {
  const query = "(max-width: 639px)";
  const read = (): HeatmapVariant => (typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches ? "mobile" : "desktop");
  const [v, setV] = useState<HeatmapVariant>(read);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(query);
    const on = () => setV(mq.matches ? "mobile" : "desktop");
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return v;
}

/** «Вторник, 14 октября 2026 · 7 ч 20 мин · 3 работы» либо «… · Нет активности». */
export function dayDescription(kind: ActivityKind, d: ActivityDay): string {
  const date = formatDateLong(d.date);
  if (d.level === 0) return `${date} · Нет активности`;
  if (kind === "hours") {
    return `${date} · ${formatDuration(d.minutes)} · ${d.works_count} ${plural(d.works_count, "работа", "работы", "работ")}`;
  }
  const a = d.actions ?? 0;
  return `${date} · ${a} ${plural(a, "действие", "действия", "действий")} · ${d.works_count} ${plural(d.works_count, "заказ", "заказа", "заказов")}`;
}

interface Cell { date: string; day: ActivityDay | null; shown: boolean }

function buildWeeks(data: ActivityHeatmapData): Cell[][] {
  const byDate = new Map<string, ActivityDay>();
  let maxDate = "";
  for (const d of data.days) {
    byDate.set(d.date, d);
    if (d.date > maxDate) maxDate = d.date;
  }
  const last = maxDate && maxDate < data.to ? maxDate : data.to; // будущие дни не показываются
  const first = data.first_day && data.first_day > data.from ? data.first_day : data.from; // до приёма — пусто
  const weeks: Cell[][] = [];
  for (let w = weekStart(data.from); w <= last; w = addDays(w, 7)) {
    const col: Cell[] = [];
    for (let i = 0; i < 7; i++) {
      const date = addDays(w, i);
      const shown = date >= first && date <= last;
      col.push({ date, shown, day: shown ? (byDate.get(date) ?? null) : null });
    }
    weeks.push(col);
  }
  return weeks;
}

function legendLabels(kind: ActivityKind, t: number[]): string[] {
  const n = (v: number | undefined) => String(v ?? 0).replace(".", ",");
  const unit = kind === "hours" ? "ч" : "действий";
  return ["0", `до ${n(t[0])}`, `до ${n(t[1])}`, `до ${n(t[2])}`, `более ${n(t[2])} ${unit}`];
}

export function HeatmapSkeleton({ variant }: { variant: HeatmapVariant }) {
  const h = MONTH_ROW + 4 + 7 * SIZE[variant] + 6 * GAP + 28 + 24;
  return <div role="status" aria-label="Загрузка" className="animate-pulse rounded-lg bg-border/40" style={{ height: h }} />;
}

/** Сетка недель × дней недели. Только отображение: данные приходят снаружи. */
export function HeatmapGrid({
  data,
  variant,
  selected,
  onSelect,
}: {
  data: ActivityHeatmapData;
  variant: HeatmapVariant;
  selected: string | null;
  onSelect: (date: string) => void;
}) {
  const size = SIZE[variant];
  const weeks = useMemo(() => buildWeeks(data), [data]);
  const shownDates = useMemo(() => weeks.flat().filter((c) => c.shown).map((c) => c.date), [weeks]);
  const [focusDate, setFocusDate] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const tabDate = focusDate && shownDates.includes(focusDate) ? focusDate : selected && shownDates.includes(selected) ? selected : (shownDates[shownDates.length - 1] ?? null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [weeks, variant]);

  const byDate = useMemo(() => new Map(weeks.flat().map((c) => [c.date, c])), [weeks]);
  const describe = (date: string): string => {
    const c = byDate.get(date);
    return dayDescription(data.kind, c?.day ?? { date, minutes: null, hours: null, actions: null, works_count: 0, level: 0, order_numbers: [] });
  };

  function move(to: string | undefined) {
    if (!to || !shownDates.includes(to)) return;
    setFocusDate(to);
    gridRef.current?.querySelector<HTMLElement>(`[data-date="${to}"]`)?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const cur = (e.target as HTMLElement).dataset.date;
    if (!cur) return;
    const delta: Record<string, number> = { ArrowLeft: -7, ArrowRight: 7, ArrowUp: -1, ArrowDown: 1 };
    if (e.key in delta) {
      e.preventDefault();
      move(addDays(cur, delta[e.key]));
    } else if (e.key === "Home") {
      e.preventDefault();
      move(shownDates[0]);
    } else if (e.key === "End") {
      e.preventDefault();
      move(shownDates[shownDates.length - 1]);
    }
  }

  // Подписи месяцев над колонкой, где месяц меняется.
  const monthLabels = useMemo(() => {
    let prev = "";
    return weeks.map((col) => {
      const ref = col.find((c) => c.shown)?.date ?? col[0].date;
      const key = ref.slice(0, 7);
      if (key === prev) return "";
      prev = key;
      return monthShort(Number(ref.slice(5, 7)) - 1);
    });
  }, [weeks]);

  const active = hover ?? selected;
  const legend = legendLabels(data.kind, data.thresholds);

  return (
    <div>
      <div ref={scrollRef} className="overflow-x-auto pb-1">
        <div className="inline-flex gap-2">
          <div aria-hidden="true" className="text-[10px] leading-none text-muted" style={{ paddingTop: MONTH_ROW + 4 }}>
            {WEEKDAY_LABELS.map((l, i) => (
              <div key={i} className="flex items-center" style={{ height: size, marginBottom: i === 6 ? 0 : GAP }}>
                {l}
              </div>
            ))}
          </div>
          <div>
            <div aria-hidden="true" className="mb-1 grid text-[10px] leading-none text-muted" style={{ gridTemplateColumns: `repeat(${weeks.length}, ${size}px)`, columnGap: GAP, height: MONTH_ROW }}>
              {monthLabels.map((l, i) => (
                <span key={i} className="whitespace-nowrap">{l}</span>
              ))}
            </div>
            <div
              ref={gridRef}
              role="group"
              aria-label="Карта активности по дням"
              onKeyDown={onKeyDown}
              onMouseLeave={() => setHover(null)}
              className="grid"
              style={{ gridAutoFlow: "column", gridTemplateRows: `repeat(7, ${size}px)`, gridTemplateColumns: `repeat(${weeks.length}, ${size}px)`, gap: GAP }}
            >
              {weeks.flat().map((c) => {
                if (!c.shown) return <span key={c.date} aria-hidden="true" style={{ width: size, height: size }} />;
                const text = describe(c.date);
                const level = (c.day?.level ?? 0) as ActivityLevel;
                return (
                  <button
                    key={c.date}
                    type="button"
                    data-date={c.date}
                    data-level={level}
                    aria-label={text}
                    aria-pressed={selected === c.date}
                    title={text}
                    tabIndex={c.date === tabDate ? 0 : -1}
                    onClick={() => {
                      setFocusDate(c.date);
                      onSelect(c.date);
                    }}
                    onMouseEnter={() => setHover(c.date)}
                    onFocus={() => setHover(c.date)}
                    onBlur={() => setHover(null)}
                    className={clsx("rounded-[2px] p-0", LEVEL_CLASS[level], selected === c.date && "ring-2 ring-fg")}
                    style={{ width: size, height: size }}
                  />
                );
              })}
            </div>
          </div>
        </div>
      </div>
      <p aria-live="polite" className="mt-2 min-h-5 text-xs text-muted">
        {active ? describe(active) : "Выберите день, чтобы увидеть подробности"}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted" aria-label="Обозначения">
        <span>Меньше</span>
        <ul className="flex items-center gap-1">
          {([0, 1, 2, 3, 4] as ActivityLevel[]).map((l) => (
            <li key={l} title={legend[l]} aria-label={legend[l]} className={clsx("rounded-[2px]", LEVEL_CLASS[l])} style={{ width: size, height: size }} />
          ))}
        </ul>
        <span>Больше</span>
        <span>· {legend.join(" · ")}</span>
      </div>
    </div>
  );
}

/** Итоги периода. */
export function HeatmapSummary({ data }: { data: ActivityHeatmapData }) {
  const s = data.summary;
  const hours = data.kind === "hours";
  const avg = s.average_per_working_day.replace(".", ",");
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-muted">Рабочих дней</dt>
        <dd className="font-medium">{s.working_days}</dd>
      </div>
      <div>
        <dt className="text-muted">{hours ? "Всего часов" : "Всего действий"}</dt>
        <dd className="font-medium">{hours ? formatHours(s.total_hours) : formatQty(String(s.total_actions ?? 0))}</dd>
      </div>
      <div>
        <dt className="text-muted">В среднем за рабочий день</dt>
        <dd className="font-medium">{hours ? `${avg}\u00A0ч` : avg}</dd>
      </div>
      <div>
        <dt className="text-muted">Самая длинная серия</dt>
        <dd className="font-medium">
          {s.longest_streak_days} {plural(s.longest_streak_days, "день", "дня", "дней")} подряд
        </dd>
      </div>
    </dl>
  );
}

function HeatmapTable({ data, selected, onSelect }: { data: ActivityHeatmapData; selected: string | null; onSelect: (date: string) => void }) {
  const rows = [...data.days].filter((d) => d.level > 0).sort((a, b) => (a.date < b.date ? 1 : -1));
  if (rows.length === 0) return <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Нет активности за выбранный период</p>;
  const hours = data.kind === "hours";
  return (
    <Table>
      <caption className="sr-only">Дни с активностью</caption>
      <thead>
        <tr>
          <Th>Дата</Th>
          <Th>{hours ? "Время" : "Действий"}</Th>
          <Th>{hours ? "Работ" : "Заказов"}</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((d) => (
          <tr key={d.date} className={selected === d.date ? "bg-bg" : undefined}>
            <Td>
              <button type="button" className="text-left underline-offset-2 hover:underline" aria-pressed={selected === d.date} onClick={() => onSelect(d.date)}>
                {formatDateLong(d.date)}
              </button>
            </Td>
            <Td>{hours ? formatDuration(d.minutes) : (d.actions ?? 0)}</Td>
            <Td>{d.works_count}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

/** Общий компонент: загрузка, карта/таблица, итоги. Список за день рисует родитель (ActivityDayList). */
export function ActivityHeatmap({
  userId,
  from,
  to,
  variant,
  selected = null,
  onSelect = () => undefined,
  showSummary = true,
  onLoaded,
}: {
  userId: string;
  from: string;
  to: string;
  variant?: HeatmapVariant;
  selected?: string | null;
  onSelect?: (date: string) => void;
  showSummary?: boolean;
  onLoaded?: (data: ActivityHeatmapData) => void;
}) {
  const auto = useHeatmapVariant();
  const v = variant ?? auto;
  const q = useActivityHeatmap(userId, from, to);
  const [asTable, setAsTable] = useState(false);
  const data = q.data;
  useEffect(() => {
    if (data) onLoaded?.(data);
  }, [data, onLoaded]);

  if (q.isLoading) return <HeatmapSkeleton variant={v} />;
  if (q.error || !data) return <LoadError error={q.error} onRetry={() => void q.refetch()} />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end">
        <Button variant="secondary" aria-pressed={asTable} onClick={() => setAsTable((x) => !x)}>
          Таблица
        </Button>
      </div>
      {asTable ? <HeatmapTable data={data} selected={selected} onSelect={onSelect} /> : <HeatmapGrid data={data} variant={v} selected={selected} onSelect={onSelect} />}
      {showSummary && <HeatmapSummary data={data} />}
    </div>
  );
}
