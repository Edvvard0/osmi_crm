/** Деньги и часы приходят строками-десятичными ("1500.00"): без float, только строковые операции. */

const NBSP = "\u00a0";
const groupThousands = (int: string) => int.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);

function split(v: string | null | undefined): { neg: boolean; int: string; frac: string } | null {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec((v ?? "").trim());
  return m ? { neg: m[1] === "-", int: m[2].replace(/^0+(?=\d)/, ""), frac: m[3] ?? "" } : null;
}

/** "1500.00" → "1 500,00 ₽" (неразрывные пробелы). */
export function formatMoney(v: string | null | undefined): string {
  const p = split(v);
  if (!p) return "—";
  return `${p.neg ? "−" : ""}${groupThousands(p.int)},${p.frac.padEnd(2, "0").slice(0, 2)}${NBSP}₽`;
}

/** "1.5" → "1,50 ч" */
export function formatHours(v: string | null | undefined): string {
  const p = split(v);
  if (!p) return "—";
  return `${p.int},${p.frac.padEnd(2, "0").slice(0, 2)}${NBSP}ч`;
}

/**
 * Ввод пользователя → строка-десятичная с ровно `scale` знаками ("1 500,5" → "1500.50").
 * Принимает запятую или точку; отрицательные, буквы и лишние знаки после запятой — null.
 */
export function parseDecimal(raw: string, scale = 2): string | null {
  const s = raw.replace(/\s/g, "").replace(",", ".");
  const m = /^(\d{1,9})(?:\.(\d*))?$/.exec(s);
  if (!m || (m[2] ?? "").length > scale) return null;
  return `${m[1].replace(/^0+(?=\d)/, "")}.${(m[2] ?? "").padEnd(scale, "0")}`;
}

/** Строка-десятичная → значение для поля ввода ("1500.00" → "1500,00"). */
export function toInput(v: string | null | undefined): string {
  return v ? v.replace(".", ",") : "";
}
