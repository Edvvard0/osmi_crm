import { useActiveLocation } from "@/features/locations/api";
import { addDays, isDateStr, todayIn, weekStart } from "@/features/appointments/time";
import { api } from "@/shared/api/client";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { formatHours, formatMoney, parseDecimal } from "@/shared/lib/money";

import type { ExportFormat, KpiKind, ReportColumnKind } from "./types";

const NBSP = " ";

export const enc = encodeURIComponent;

export function qs(o: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/* ---------- Числа ---------- */

const group = (int: string) => int.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);

/** "1234" → "1 234"; нечисло → "—". */
export function formatInt(v: string | number | null | undefined): string {
  const m = /^(-?)(\d+)(?:\.\d+)?$/.exec(String(v ?? "").trim());
  return m ? `${m[1] ? "−" : ""}${group(m[2].replace(/^0+(?=\d)/, ""))}` : "—";
}

/** "12.50" → "12,50 %". */
export function formatPercent(v: string | null | undefined): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec((v ?? "").trim());
  if (!m) return "—";
  return `${m[1] ? "−" : ""}${group(m[2])},${(m[3] ?? "").padEnd(2, "0").slice(0, 2)}${NBSP}%`;
}

/** Число с дробной частью без лишних нулей: "3.500" → "3,5", "4.00" → "4". */
export function formatQty(v: string | null | undefined): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec((v ?? "").trim());
  if (!m) return "—";
  const frac = (m[3] ?? "").replace(/0+$/, "");
  return `${m[1] ? "−" : ""}${group(m[2].replace(/^0+(?=\d)/, ""))}${frac ? `,${frac}` : ""}`;
}

/** Значение ячейки отчёта по типу колонки. Значения подставляются только как текст. */
export function formatCell(v: string | null | undefined, kind: ReportColumnKind): string {
  if (v === null || v === undefined || v === "") return "—";
  switch (kind) {
    case "money": return formatMoney(v);
    case "hours": return formatHours(v);
    case "count": return formatQty(v);
    case "percent": return formatPercent(v);
    case "date": return formatDate(v);
    default: return v;
  }
}

/** Изменение к прошлому периоду: «▲ 12,50 %» / «▼ 3,20 п.п.»; null → «—». */
export function formatDelta(kind: KpiKind, delta: string | null): { text: string; sign: -1 | 0 | 1 } {
  if (delta === null || delta === undefined) return { text: "—", sign: 0 };
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(delta.trim());
  if (!m) return { text: "—", sign: 0 };
  const abs = `${m[2]},${(m[3] ?? "").padEnd(2, "0").slice(0, 2)}`;
  const zero = /^0+,0+$/.test(abs);
  const unit = kind === "percent" ? "п.п." : "%";
  if (zero) return { text: `0${NBSP}${unit}`, sign: 0 };
  return m[1] ? { text: `▼${NBSP}${abs}${NBSP}${unit}`, sign: -1 } : { text: `▲${NBSP}${abs}${NBSP}${unit}`, sign: 1 };
}

/** Целые минуты → «7 ч 20 мин» / «45 мин» / «0 мин». */
export function formatDuration(minutes: number | null | undefined): string {
  const n = Math.max(0, Math.round(minutes ?? 0));
  const h = Math.floor(n / 60);
  const m = n % 60;
  if (h && m) return `${h}${NBSP}ч ${m}${NBSP}мин`;
  if (h) return `${h}${NBSP}ч`;
  return `${m}${NBSP}мин`;
}

/** Склонение по числу: plural(3, "работа", "работы", "работ") → "работы". */
export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

/** Знак десятичной строки без float. */
export function sign(v: string | null | undefined): -1 | 0 | 1 {
  const s = (v ?? "").trim();
  if (!/^-?\d+(\.\d+)?$/.test(s)) return 0;
  if (/^-?0+(\.0+)?$/.test(s)) return 0;
  return s.startsWith("-") ? -1 : 1;
}

/** Подписанная сумма: «+1 000,00 ₽» / «−500,00 ₽». */
export function formatSigned(v: string | null | undefined): string {
  return sign(v) > 0 ? `+${formatMoney(v)}` : formatMoney(v);
}

/** Ввод суммы со знаком ("−500", "+1 000,5") → "-500.00" / "1000.50"; ноль и мусор → null. */
export function parseSigned(raw: string): string | null {
  const t = raw.trim().replace(/^[−–]/, "-").replace(/^\+/, "");
  const neg = t.startsWith("-");
  const d = parseDecimal(neg ? t.slice(1) : t, 2);
  if (d === null || /^0+\.0+$/.test(d)) return null;
  return neg ? `-${d}` : d;
}

/** Строка с точкой → число для графика (только отрисовка, не финансовые расчёты). */
export const num = (v: string | null | undefined): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/* ---------- Даты ---------- */

const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const MONTHS_NOM = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const WEEKDAYS = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];

export const monthShort = (m0: number) => MONTHS_SHORT[m0] ?? "";

function ymd(date: string): [number, number, number] | null {
  if (!isDateStr(date)) return null;
  const [y, m, d] = date.split("-").map(Number);
  return [y, m, d];
}

/** "2026-11-09" → "09.11.2026". Не дата (например, текст) возвращается как есть. */
export function formatDate(date: string | null | undefined): string {
  const p = ymd(date ?? "");
  return p ? `${String(p[2]).padStart(2, "0")}.${String(p[1]).padStart(2, "0")}.${p[0]}` : (date ?? "—");
}

export function formatDateShort(date: string): string {
  const p = ymd(date);
  return p ? `${String(p[2]).padStart(2, "0")}.${String(p[1]).padStart(2, "0")}` : date;
}

/** "2026-10-14" → "Вторник, 14 октября 2026". */
export function formatDateLong(date: string): string {
  const p = ymd(date);
  if (!p) return date;
  const wd = new Date(Date.UTC(p[0], p[1] - 1, p[2])).getUTCDay();
  return `${WEEKDAYS[wd]}, ${p[2]} ${MONTHS_GEN[p[1] - 1]} ${p[0]}`;
}

/** "2026-11" → "ноябрь 2026". */
export function formatMonth(month: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  return m ? `${MONTHS_NOM[Number(m[2]) - 1] ?? m[2]} ${m[1]}` : month;
}

export const isMonth = (s: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(s);

export function shiftMonth(month: string, delta: number): string {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  if (!m) return month;
  const t = Number(m[1]) * 12 + (Number(m[2]) - 1) + delta;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}

export const monthOf = (date: string) => date.slice(0, 7);
export const firstOfMonth = (date: string) => `${date.slice(0, 7)}-01`;
export function lastOfMonth(month: string): string {
  return addDays(`${shiftMonth(month, 1)}-01`, -1);
}

/** ISO-момент → "09.11 14:30" в заданном поясе. */
export function formatTime(iso: string | null | undefined, tz: string): string {
  const ms = Date.parse(iso ?? "");
  if (Number.isNaN(ms)) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", { timeZone: tz, hour: "2-digit", minute: "2-digit" }).format(ms);
  } catch {
    return "—";
  }
}

export type PeriodKind = "today" | "week" | "month" | "custom";
export const PERIOD_LABELS: Record<PeriodKind, string> = { today: "Сегодня", week: "Неделя", month: "Месяц", custom: "Свой период" };

export function periodRange(kind: Exclude<PeriodKind, "custom">, today: string): { from: string; to: string } {
  if (kind === "today") return { from: today, to: today };
  if (kind === "week") return { from: weekStart(today), to: today };
  return { from: firstOfMonth(today), to: today };
}

/** Сегодняшняя дата в поясе выбранной точки (для «Все точек» — первой доступной, иначе Москва). */
export function useToday(): string {
  const { current, items } = useActiveLocation();
  const tz = current?.timezone ?? items[0]?.timezone ?? "Europe/Moscow";
  return todayIn(tz, Date.now());
}

/* ---------- Ошибки ---------- */

const FIELD_TEXT: Record<string, string> = {
  date_from: "Недопустимая дата начала периода",
  date_to: "Конец периода не раньше начала, не более 366 суток",
  to: "Конец периода не раньше начала, не более 366 суток",
  amount: "Сумма: число, не равное нулю, до двух знаков после запятой",
  reason: "Причина: от 1 до 500 символов",
  user_id: "Выберите сотрудника",
  month: "Месяц: не в будущем",
  valid_from: "Дата начала: не раньше первого числа текущего месяца",
  valid_to: "Дата окончания: не раньше начала и не раньше первого числа текущего месяца",
  export: "Слишком много строк для выгрузки — сократите период или уточните фильтры",
};

/** Подпись ошибки поля: сначала словарь модуля, затем общий словарь. Серверный текст не используется. */
export function reportFieldText(e: AppError | null | undefined, name: string): string | undefined {
  if (!e || e.fields[name] === undefined) return undefined;
  return FIELD_TEXT[name] ?? fieldMessage(e, name);
}

/** Текст ошибки запроса для баннера: ошибки полей периода объясняются, остальное — из словаря. */
export function reportErrorText(err: unknown): string {
  const e = toAppError(err);
  if (e.code === "validation_error") {
    const texts = Object.keys(e.fields).map((n) => reportFieldText(e, n)).filter(Boolean);
    if (texts.length) return texts.join(". ");
  }
  return e.message;
}

/* ---------- Скачивание ---------- */

/** Файл скачивается через api() как Blob (нужен Authorization) и сохраняется по blob:-ссылке. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const blob = await api<Blob>(path, { blob: true });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export const EXPORT_FORMATS: ExportFormat[] = ["xlsx", "csv"];
