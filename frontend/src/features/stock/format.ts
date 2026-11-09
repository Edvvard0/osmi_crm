import { type AppError } from "@/shared/api/errors";
import { PART_UNIT_LABELS, type PartUnit } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/money";

/** "5.000" → "5", "2.500" → "2,5" (количества на складе без хвостовых нулей). */
export function fmtQty(v: string | null | undefined): string {
  if (!v) return "—";
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(v.trim());
  if (!m) return "—";
  const frac = (m[3] ?? "").replace(/0+$/, "");
  const int = m[2].replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${m[1] === "-" ? "−" : ""}${int}${frac ? `,${frac}` : ""}`;
}

/** Знаковое количество движения: "+2,5" / "−1". */
export function fmtSignedQty(v: string): string {
  const s = fmtQty(v);
  return v.trim().startsWith("-") || s === "0" ? s : `+${s}`;
}

export const unitLabel = (u: PartUnit | string): string => PART_UNIT_LABELS[u as PartUnit] ?? String(u);

/** Количество: строка с 3 знаками, строго > 0, иначе null. */
export function parseQty(raw: string): string | null {
  const v = parseDecimal(raw, 3);
  return v !== null && /[1-9]/.test(v) ? v : null;
}

/** Количество >= 0 (фактический остаток, минимум). */
export function parseQtyOrZero(raw: string): string | null {
  return parseDecimal(raw, 3);
}

function toCents(v: string): bigint {
  return BigInt(v.replace(".", ""));
}

export function toMoney(cents: bigint): string {
  const neg = cents < 0n;
  const abs = neg ? -cents : cents;
  const s = abs.toString().padStart(3, "0");
  return `${neg ? "-" : ""}${s.slice(0, -2)}.${s.slice(-2)}`;
}

/** Сумма строки: количество (3 знака) × цена (2 знака), ROUND_HALF_UP до копеек, без float. */
export function lineTotal(qty: string, price: string): string {
  const prod = toCents(qty) * toCents(price); // 5 знаков после запятой
  return toMoney((prod + 500n) / 1000n);
}

export function sumMoney(values: string[]): string {
  return toMoney(values.reduce((a, v) => a + toCents(v), 0n));
}

/** Сравнение десятичных строк с 3 знаками. */
export const qtyEq = (a: string, b: string): boolean => toCents(a) === toCents(b);

/** Значение для поля ввода: "2.500" → "2,5". */
export const toQtyInput = (v: string): string => fmtQty(v).replace(/ /g, "");

/**
 * Текст ошибки нехватки остатка из details (нужно / доступно), с названием, если оно известно.
 * Пригоден и для заказ-наряда: «Недостаточно на складе: нужно N, доступно M».
 */
export function stockErrorText(e: AppError, partName?: (id: string) => string | undefined): string | null {
  if (e.code !== "insufficient_stock") return null;
  const { part_id, available, requested } = e.details;
  const name = part_id ? partName?.(part_id) : undefined;
  if (available === undefined || requested === undefined) return e.message;
  return `Недостаточно на складе${name ? ` («${name}»)` : ""}: нужно ${fmtQty(requested)}, доступно ${fmtQty(available)}`;
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Количество из поля ввода + 1 (повторный скан одной позиции); невалидное значение считается нулём. */
export function incQty(raw: string): string {
  const v = parseQty(raw) ?? "0.000";
  const s = (toCents(v) + 1000n).toString().padStart(4, "0");
  return toQtyInput(`${s.slice(0, -3)}.${s.slice(-3)}`);
}

/** Денежное поле (2 знака, >= 0) или null. */
export const parseDecimalOrNull = (raw: string): string | null => parseDecimal(raw, 2);

/** Разница a − b для количеств с 3 знаками: "+2,5" / "−1". */
export function diffQty(a: string, b: string): string {
  const n = toCents(a) - toCents(b);
  const abs = (n < 0n ? -n : n).toString().padStart(4, "0");
  return fmtSignedQty(`${n < 0n ? "-" : ""}${abs.slice(0, -3)}.${abs.slice(-3)}`);
}
