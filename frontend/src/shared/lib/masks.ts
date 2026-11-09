/** Маски и нормализация ввода (клиентская часть; финальная нормализация — на сервере). */

/** Национальная часть номера: 10 цифр без кода страны. */
export function phoneNational(raw: string): string {
  let d = raw.replace(/\D/g, "");
  if (d.startsWith("7") || d.startsWith("8")) d = d.slice(1);
  return d.slice(0, 10);
}

/** Маска «+7 (999) 123-45-67» — вызывается на каждый ввод. */
export function maskPhone(raw: string): string {
  const n = phoneNational(raw);
  if (!n) return "";
  let out = `+7 (${n.slice(0, 3)}`;
  if (n.length >= 3) out += ")";
  if (n.length > 3) out += ` ${n.slice(3, 6)}`;
  if (n.length > 6) out += `-${n.slice(6, 8)}`;
  if (n.length > 8) out += `-${n.slice(8, 10)}`;
  return out;
}

/** Любой формат → E.164 (+7XXXXXXXXXX) или null, если номер неполный. */
export function normalizePhone(raw: string): string | null {
  const n = phoneNational(raw);
  return n.length === 10 ? `+7${n}` : null;
}

const LAT_TO_CYR: Record<string, string> = {
  A: "А", B: "В", E: "Е", K: "К", M: "М", H: "Н", O: "О", P: "Р", C: "С", T: "Т", Y: "У", X: "Х",
};

/** Госномер: верхний регистр, без пробелов и знаков, похожая латиница → кириллица. */
export function normalizePlate(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/[^0-9A-ZА-ЯЁ]/g, "")
    .replace(/[A-Z]/g, (c) => LAT_TO_CYR[c] ?? c)
    .slice(0, 10);
}

export function maskVin(raw: string): string {
  return raw.toUpperCase().replace(/[^0-9A-Z]/g, "").slice(0, 17);
}

/** VIN: ровно 17 символов, без I, O, Q. */
export function isValidVin(v: string): boolean {
  return /^[A-HJ-NPR-Z0-9]{17}$/.test(v);
}

export function isValidInn(v: string): boolean {
  return /^(\d{10}|\d{12})$/.test(v);
}

export function isValidEmail(v: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}
