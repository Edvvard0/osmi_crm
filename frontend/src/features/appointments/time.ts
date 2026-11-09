/**
 * Время в часовом поясе точки без внешних библиотек: всё считается через Intl.DateTimeFormat.
 * Дата — строка "YYYY-MM-DD", время суток — минуты от полуночи, момент — миллисекунды UTC.
 */

const FALLBACK_TZ = "UTC";
const fmtCache = new Map<string, Intl.DateTimeFormat>();
const validCache = new Map<string, boolean>();

/** Неизвестный пояс не должен ронять экран. */
export function safeZone(tz: string): string {
  let ok = validCache.get(tz);
  if (ok === undefined) {
    try {
      new Intl.DateTimeFormat("en-US", { timeZone: tz });
      ok = true;
    } catch {
      ok = false;
    }
    validCache.set(tz, ok);
  }
  return ok ? tz : FALLBACK_TZ;
}

function formatter(tz: string): Intl.DateTimeFormat {
  const zone = safeZone(tz);
  let f = fmtCache.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    fmtCache.set(zone, f);
  }
  return f;
}

export interface ZoneParts {
  y: number;
  mo: number;
  d: number;
  h: number;
  mi: number;
  s: number;
}

export function zoneParts(ms: number, tz: string): ZoneParts {
  const out: Record<string, number> = {};
  for (const p of formatter(tz).formatToParts(new Date(ms))) {
    if (p.type !== "literal") out[p.type] = Number(p.value);
  }
  return { y: out.year, mo: out.month, d: out.day, h: (out.hour ?? 0) % 24, mi: out.minute, s: out.second };
}

/** Смещение пояса от UTC в минутах на заданный момент (для Москвы 180). */
export function zoneOffsetMin(ms: number, tz: string): number {
  const p = zoneParts(ms, tz);
  const asUtc = Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s);
  return Math.round((asUtc - Math.floor(ms / 1000) * 1000) / 60000);
}

const pad = (n: number, w = 2) => String(n).padStart(w, "0");

export function formatOffset(min: number): string {
  const sign = min < 0 ? "-" : "+";
  const a = Math.abs(min);
  return `${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

/** Дата и минуты суток в поясе → момент UTC (учитывает переход на летнее время). */
export function zonedTimeToMs(date: string, minutes: number, tz: string): number {
  const [y, m, d] = date.split("-").map(Number);
  const naive = Date.UTC(y, m - 1, d, 0, minutes);
  const first = naive - zoneOffsetMin(naive, tz) * 60000;
  return naive - zoneOffsetMin(first, tz) * 60000;
}

/** Момент → ISO 8601 со смещением пояса точки: 2026-11-10T10:00:00+03:00. */
export function toZonedIso(ms: number, tz: string): string {
  const p = zoneParts(ms, tz);
  return `${pad(p.y, 4)}-${pad(p.mo)}-${pad(p.d)}T${pad(p.h)}:${pad(p.mi)}:${pad(p.s)}${formatOffset(zoneOffsetMin(ms, tz))}`;
}

export function dateOfMs(ms: number, tz: string): string {
  const p = zoneParts(ms, tz);
  return `${pad(p.y, 4)}-${pad(p.mo)}-${pad(p.d)}`;
}

export function minuteOfDay(ms: number, tz: string): number {
  const p = zoneParts(ms, tz);
  return p.h * 60 + p.mi;
}

/** Минуты суток → "HH:MM". Значения вне суток не нормализуются. */
export function hhmm(min: number): string {
  return `${pad(Math.floor(min / 60))}:${pad(min % 60)}`;
}

/** "HH:MM" или "HH:MM:SS" → минуты от полуночи; мусор → null. */
export function parseHm(s: string): number | null {
  const m = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(s.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const mi = Number(m[2]);
  return h > 23 || mi > 59 ? null : h * 60 + mi;
}

export function isDateStr(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

export function addDays(date: string, n: number): string {
  const [y, m, d] = date.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return `${pad(t.getUTCFullYear(), 4)}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** Понедельник недели, в которую попадает дата. */
export function weekStart(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = воскресенье
  return addDays(date, -((wd + 6) % 7));
}

export function weekDates(date: string): string[] {
  const s = weekStart(date);
  return Array.from({ length: 7 }, (_, i) => addDays(s, i));
}

export function todayIn(tz: string, nowMs: number): string {
  return dateOfMs(nowMs, tz);
}

const dayFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: "UTC", weekday: "short", day: "numeric", month: "long" });
const dayShortFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: "UTC", weekday: "short", day: "numeric", month: "numeric" });

function noonUtc(date: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 12));
}

/** «вт, 10 ноября» */
export function formatDay(date: string): string {
  return dayFmt.format(noonUtc(date));
}

/** «вт, 10.11» */
export function formatDayShort(date: string): string {
  return dayShortFmt.format(noonUtc(date));
}

export function formatTimeRange(startMs: number, endMs: number, tz: string): string {
  return `${hhmm(minuteOfDay(startMs, tz))}–${hhmm(minuteOfDay(endMs, tz))}`;
}
