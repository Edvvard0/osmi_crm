/** Чистая математика сетки календаря: интервалы, перенос, растягивание, дорожки, валидация. Минуты — от полуночи. */

export const STEP = 15;
export const PX_PER_MIN = 1.6;
export const MIN_DURATION = 15;
export const MAX_DURATION = 12 * 60;
export const FORM_STEP = 5;

export interface Interval {
  start: number;
  end: number;
}

/** Полуоткрытые интервалы [start, end): конец одной записи = начало другой — не пересечение. */
export function overlaps(a: Interval, b: Interval): boolean {
  return a.start < b.end && b.start < a.end;
}

export function snap(min: number, step = STEP, mode: "round" | "floor" | "ceil" = "round"): number {
  const k = min / step;
  return (mode === "floor" ? Math.floor(k) : mode === "ceil" ? Math.ceil(k) : Math.round(k)) * step;
}

/** Перенос: длительность сохраняется, начало привязывается к шагу и не выходит за границы диапазона. */
export function clampMove(iv: Interval, deltaMin: number, range: Interval, step = STEP): Interval {
  const dur = iv.end - iv.start;
  const maxStart = Math.max(range.start, range.end - dur);
  const start = Math.min(Math.max(snap(iv.start + deltaMin, step), range.start), snap(maxStart, step, "floor"));
  return { start, end: start + dur };
}

/** Растягивание нижнего края: минимум 15 минут, максимум 12 часов и конец рабочего диапазона. */
export function clampResize(iv: Interval, deltaMin: number, range: Interval, step = STEP): Interval {
  const maxEnd = Math.min(range.end, iv.start + MAX_DURATION);
  const end = Math.min(Math.max(snap(iv.end + deltaMin, step), iv.start + Math.max(step, MIN_DURATION)), snap(maxEnd, step, "floor"));
  return { start: iv.start, end: Math.max(end, iv.start + MIN_DURATION) };
}

export interface Laned<T> {
  item: T;
  lane: number;
  lanes: number;
}

/** Раскладка пересекающихся карточек одной колонки по дорожкам (плечом к плечу). */
export function assignLanes<T extends Interval>(items: T[]): Laned<T>[] {
  const sorted = [...items].sort((a, b) => a.start - b.start || a.end - b.end);
  const out: Laned<T>[] = [];
  let cluster: Laned<T>[] = [];
  let clusterEnd = -Infinity;
  const laneEnds: number[] = [];

  const flush = () => {
    for (const c of cluster) c.lanes = Math.max(laneEnds.length, 1);
    cluster = [];
    laneEnds.length = 0;
  };

  for (const item of sorted) {
    if (item.start >= clusterEnd) {
      flush();
      clusterEnd = -Infinity;
    }
    let lane = laneEnds.findIndex((e) => e <= item.start);
    if (lane === -1) lane = laneEnds.length;
    laneEnds[lane] = item.end;
    clusterEnd = Math.max(clusterEnd, item.end);
    const l: Laned<T> = { item, lane, lanes: 1 };
    cluster.push(l);
    out.push(l);
  }
  flush();
  return out;
}

/** Длительность по умолчанию: сумма duration_minutes выбранных услуг (с округлением вверх до 5 минут), иначе 60. */
export function defaultDurationMinutes(services: { duration_minutes: number }[]): number {
  const sum = services.reduce((a, s) => a + (Number.isFinite(s.duration_minutes) ? s.duration_minutes : 0), 0);
  if (sum <= 0) return 60;
  return Math.min(Math.max(snap(sum, FORM_STEP, "ceil"), MIN_DURATION), MAX_DURATION);
}

/** Диапазон сетки: рабочие часы, расширенные, если запись выходит за них (например, часы потом сократили). */
export function gridRange(work: Interval, items: Interval[]): Interval {
  let start = work.start;
  let end = work.end;
  for (const i of items) {
    start = Math.min(start, snap(i.start, 60, "floor"));
    end = Math.max(end, snap(i.end, 60, "ceil"));
  }
  return { start: Math.max(0, start), end: Math.min(24 * 60, end) };
}

export type TimeError = "order" | "too_short" | "too_long" | "step" | "work_hours";

/** Зеркало правил контракта; сервер остаётся источником истины. */
export function validateInterval(iv: Interval, work: Interval): TimeError | null {
  if (iv.end <= iv.start) return "order";
  if (iv.start % FORM_STEP !== 0 || iv.end % FORM_STEP !== 0) return "step";
  const dur = iv.end - iv.start;
  if (dur < MIN_DURATION) return "too_short";
  if (dur > MAX_DURATION) return "too_long";
  if (iv.start < work.start || iv.end > work.end) return "work_hours";
  return null;
}

export const TIME_ERROR_TEXT: Record<TimeError, string> = {
  order: "Окончание должно быть позже начала",
  too_short: "Длительность не меньше 15 минут",
  too_long: "Длительность не больше 12 часов",
  step: "Время кратно 5 минутам",
  work_hours: "Запись должна укладываться в рабочие часы точки",
};

/** Позиция/высота карточки в пикселях относительно начала сетки. */
export function cardBox(iv: Interval, range: Interval): { top: number; height: number } {
  const s = Math.max(iv.start, range.start);
  const e = Math.min(iv.end, range.end);
  return { top: (s - range.start) * PX_PER_MIN, height: Math.max((e - s) * PX_PER_MIN, 12) };
}
