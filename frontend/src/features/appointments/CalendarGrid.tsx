import clsx from "clsx";
import { type KeyboardEvent, type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";

import { APPOINTMENT_STATUS_LABELS, type Appointment, type Department } from "@/shared/api/types";

import { isEditable } from "./api";
import { type Interval, PX_PER_MIN, STEP, assignLanes, cardBox, clampMove, clampResize } from "./grid";
import { StatusMark, statusBoxClass, struckClass, vehicleTitle } from "./status";
import { dateOfMs, hhmm, minuteOfDay } from "./time";

export interface CalendarColumn {
  key: string;
  label: string;
  sub?: string;
  /** Дата колонки (YYYY-MM-DD в поясе точки). */
  date: string;
  /** Пост колонки; null — «без поста». */
  postId: string | null;
  /** Отдел поста: перенос записи на пост другого отдела не принимается. */
  department?: Department;
}

export interface MovePayload {
  appointment: Appointment;
  column: CalendarColumn;
  interval: Interval;
}

interface Props {
  tz: string;
  columns: CalendarColumn[];
  appointments: Appointment[];
  /** Рабочие часы точки, минуты суток. */
  work: Interval;
  /** Видимый диапазон сетки (рабочие часы, расширенные при необходимости). */
  range: Interval;
  now: number;
  colKeyOf: (a: Appointment) => string;
  onCreate: (column: CalendarColumn, startMin: number) => void;
  onOpen: (a: Appointment) => void;
  onMove: (p: MovePayload) => void;
}

interface Preview {
  id: string;
  colKey: string;
  iv: Interval;
}

const MIN_COL_PX = 140;
const GUTTER_PX = 56;

export function CalendarGrid({ tz, columns, appointments, work, range, now, colKeyOf, onCreate, onOpen, onMove }: Props) {
  const colEls = useRef(new Map<string, HTMLDivElement>());
  const suppressClick = useRef(false);
  const cleanup = useRef<(() => void) | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);

  // Снять обработчики, если страница закрылась во время перетаскивания.
  useEffect(() => () => cleanup.current?.(), []);

  const totalMin = range.end - range.start;
  const bodyPx = totalMin * PX_PER_MIN;
  const hours: number[] = [];
  for (let m = Math.ceil(range.start / 60) * 60; m < range.end; m += 60) hours.push(m);
  const slots: number[] = [];
  for (let m = range.start; m < range.end; m += STEP) slots.push(m);
  const today = dateOfMs(now, tz);
  const nowMin = minuteOfDay(now, tz);

  function columnAt(x: number): CalendarColumn | null {
    for (const c of columns) {
      const r = colEls.current.get(c.key)?.getBoundingClientRect();
      if (r && x >= r.left && x < r.right) return c;
    }
    return null;
  }

  function begin(e: ReactPointerEvent, a: Appointment, mode: "move" | "resize") {
    // Перетаскивание только мышью и пером; сенсорный экран прокручивает сетку, правка — через форму записи.
    if (e.pointerType === "touch" || (e.button !== undefined && e.button !== 0) || !isEditable(a.status)) return;
    if (mode === "resize") e.stopPropagation();
    cleanup.current?.();

    const origin: Interval = { start: minuteOfDay(Date.parse(a.start_at), tz), end: minuteOfDay(Date.parse(a.end_at), tz) };
    const originKey = colKeyOf(a);
    const x0 = e.clientX;
    const y0 = e.clientY;
    let moved = false;
    let last: Preview | null = null;

    const onPointerMove = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      const dy = ev.clientY - y0;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      const delta = dy / PX_PER_MIN;
      let colKey = originKey;
      let iv: Interval;
      if (mode === "move") {
        const hit = columnAt(ev.clientX);
        // На пост другого отдела запись не переносится: остаётся в своей колонке.
        if (hit && (hit.key === originKey || !hit.department || hit.department === a.department)) colKey = hit.key;
        iv = clampMove(origin, delta, range);
      } else {
        iv = clampResize(origin, delta, range);
      }
      last = { id: a.id, colKey, iv };
      setPreview(last);
    };
    const finish = (commit: boolean) => {
      cleanup.current?.();
      setPreview(null);
      if (moved) {
        suppressClick.current = true;
        setTimeout(() => (suppressClick.current = false), 0);
      }
      const fin = last;
      if (!commit || !moved || !fin) return;
      const column = columns.find((c) => c.key === fin.colKey);
      if (!column) return;
      if (fin.colKey === originKey && fin.iv.start === origin.start && fin.iv.end === origin.end) return;
      onMove({ appointment: a, column, interval: fin.iv });
    };
    const onUp = () => finish(true);
    const onCancel = () => finish(false);

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    cleanup.current = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      cleanup.current = null;
    };
  }

  function onCardKey(e: KeyboardEvent, a: Appointment) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(a);
    }
  }

  // Запись, перетаскиваемая сейчас, показывается на новом месте.
  const placed = appointments.map((a) => {
    const base: Preview = {
      id: a.id,
      colKey: colKeyOf(a),
      iv: { start: minuteOfDay(Date.parse(a.start_at), tz), end: minuteOfDay(Date.parse(a.end_at), tz) },
    };
    const live = preview?.id === a.id;
    return { a, colKey: live ? preview.colKey : base.colKey, start: live ? preview.iv.start : base.iv.start, end: live ? preview.iv.end : base.iv.end, live };
  });

  return (
    <div className="max-h-[calc(100vh-14rem)] min-h-[20rem] overflow-auto rounded-lg border border-border bg-surface" data-testid="calendar-grid">
      <div style={{ minWidth: GUTTER_PX + columns.length * MIN_COL_PX }}>
        <div className="sticky top-0 z-20 flex border-b border-border bg-surface">
          <div className="sticky left-0 z-10 shrink-0 bg-surface" style={{ width: GUTTER_PX }} />
          {columns.map((c) => (
            <div key={c.key} className="min-w-0 flex-1 border-l border-border px-2 py-2 text-sm" style={{ minWidth: MIN_COL_PX }}>
              <div className="truncate font-medium">{c.label}</div>
              {c.sub && <div className="truncate text-xs text-muted">{c.sub}</div>}
            </div>
          ))}
        </div>
        <div className="flex">
          <div className="sticky left-0 z-10 shrink-0 bg-surface" style={{ width: GUTTER_PX, height: bodyPx }} aria-hidden="true">
            <div className="relative h-full">
              {hours.map((m) => (
                <div key={m} className="absolute right-2 -translate-y-1/2 text-xs text-muted" style={{ top: (m - range.start) * PX_PER_MIN }}>
                  {hhmm(m)}
                </div>
              ))}
            </div>
          </div>
          {columns.map((c) => {
            const inCol = placed.filter((p) => p.colKey === c.key);
            const lanes = assignLanes(inCol);
            return (
              <div
                key={c.key}
                data-col={c.key}
                ref={(el) => {
                  if (el) colEls.current.set(c.key, el);
                  else colEls.current.delete(c.key);
                }}
                className="relative flex-1 border-l border-border"
                style={{ minWidth: MIN_COL_PX, height: bodyPx }}
              >
                {slots.map((m) => {
                  const open = m >= work.start && m < work.end;
                  return (
                    <button
                      key={m}
                      type="button"
                      tabIndex={-1}
                      disabled={!open}
                      aria-label={`Создать запись: ${c.label}, ${c.sub ? `${c.sub}, ` : ""}${hhmm(m)}`}
                      onClick={() => onCreate(c, m)}
                      style={{ height: STEP * PX_PER_MIN }}
                      className={clsx(
                        "block w-full border-t",
                        m % 60 === 0 ? "border-border" : "border-dashed border-border/50",
                        open ? "hover:bg-accent/5" : "cursor-not-allowed bg-border/30",
                      )}
                    />
                  );
                })}
                {c.date === today && nowMin >= range.start && nowMin <= range.end && (
                  <div
                    data-testid="now-line"
                    aria-hidden="true"
                    className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-danger"
                    style={{ top: (nowMin - range.start) * PX_PER_MIN }}
                  />
                )}
                {lanes.map(({ item, lane, lanes: n }) => {
                  const a = item.a;
                  const box = cardBox({ start: item.start, end: item.end }, range);
                  const editable = isEditable(a.status);
                  const time = `${hhmm(item.start)}–${hhmm(item.end)}`;
                  const tall = box.height >= 44;
                  return (
                    <div
                      key={a.id}
                      role="button"
                      tabIndex={0}
                      data-appointment={a.id}
                      aria-label={`${time}, ${vehicleTitle(a)}, ${a.client.full_name}, ${APPOINTMENT_STATUS_LABELS[a.status]}`}
                      title={`${time} · ${vehicleTitle(a)} · ${a.client.full_name}${a.services.length ? ` · ${a.services.map((s) => s.name).join(", ")}` : ""}`}
                      onPointerDown={(e) => begin(e, a, "move")}
                      onClick={() => {
                        if (!suppressClick.current) onOpen(a);
                      }}
                      onKeyDown={(e) => onCardKey(e, a)}
                      className={clsx(
                        "absolute z-[5] select-none overflow-hidden rounded border border-border px-1.5 py-0.5 text-xs shadow-sm focus-visible:z-20",
                        statusBoxClass(a.status),
                        editable ? "cursor-grab" : "cursor-pointer",
                        item.live && "z-20 opacity-80 ring-2 ring-accent",
                      )}
                      style={{
                        top: box.top,
                        height: box.height,
                        left: `calc(${(lane / n) * 100}% + 2px)`,
                        width: `calc(${100 / n}% - 4px)`,
                      }}
                    >
                      <div className={clsx("flex items-center gap-1", struckClass(a.status))}>
                        <span className="font-medium tabular-nums">{time}</span>
                        <StatusMark status={a.status} />
                      </div>
                      <div className={clsx("truncate font-medium", struckClass(a.status))}>{vehicleTitle(a)}</div>
                      {tall && <div className={clsx("truncate text-muted", struckClass(a.status))}>{a.client.full_name}</div>}
                      {box.height >= 76 && a.services.length > 0 && (
                        <div className={clsx("truncate text-muted", struckClass(a.status))}>{a.services.map((s) => s.name).join(", ")}</div>
                      )}
                      {editable && (
                        <span
                          aria-hidden="true"
                          data-resize={a.id}
                          onPointerDown={(e) => begin(e, a, "resize")}
                          className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize bg-border/60 hover:bg-border"
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
