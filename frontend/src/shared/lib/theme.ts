import { readPref, writePref } from "./storage";

export type Theme = "system" | "light" | "dark";
const KEY = "crm.theme";

export function getTheme(): Theme {
  const v = readPref(KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export function applyTheme(t: Theme): void {
  const el = document.documentElement;
  if (t === "system") el.removeAttribute("data-theme");
  else el.setAttribute("data-theme", t);
}

export function setTheme(t: Theme): void {
  writePref(KEY, t);
  applyTheme(t);
}
