/**
 * Определяет, есть ли на экране форма с несохранённым вводом (для предупреждения перед обновлением версии).
 * Форма считается «грязной» после ввода пользователем и «чистой» после отправки, сброса или удаления из DOM.
 */
const dirty = new Set<Element>();
let installed = false;

function container(t: EventTarget | null): Element | null {
  return t instanceof Element ? t.closest("form, dialog") : null;
}

export function installDirtyFormTracking(): void {
  if (installed || typeof document === "undefined") return;
  installed = true;
  const mark = (e: Event) => {
    const c = container(e.target);
    if (c) dirty.add(c);
  };
  document.addEventListener("input", mark, true);
  document.addEventListener("change", mark, true);
  const clear = (e: Event) => {
    const c = container(e.target) ?? (e.target instanceof Element ? e.target : null);
    if (c) dirty.delete(c);
  };
  document.addEventListener("submit", clear, true);
  document.addEventListener("reset", clear, true);
}

export function hasUnsavedForm(): boolean {
  for (const el of [...dirty]) {
    if (!el.isConnected) dirty.delete(el);
  }
  return dirty.size > 0;
}

export function resetDirtyFormsForTests(): void {
  dirty.clear();
}
