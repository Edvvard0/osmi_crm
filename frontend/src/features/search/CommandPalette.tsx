import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useGlobalSearch } from "@/features/clients/api";
import { toAppError } from "@/shared/api/errors";
import type { SearchHit } from "@/shared/api/types";
import { Button } from "@/shared/ui/ui";

export function hitPath(h: SearchHit): string {
  return h.type === "client" ? `/clients/${encodeURIComponent(h.id)}` : `/vehicles/${encodeURIComponent(h.id)}`;
}

/** Кнопка в шапке + палитра глобального поиска по Ctrl+K (⌘K). */
export function GlobalSearch() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <Button variant="secondary" aria-label="Глобальный поиск" onClick={() => setOpen(true)}>
        <span aria-hidden="true">🔍</span>
        <span className="hidden sm:inline">Поиск</span>
        <kbd className="hidden rounded border border-border px-1 text-xs text-muted sm:inline">Ctrl+K</kbd>
      </Button>
      {open && <Palette onClose={() => setOpen(false)} />}
    </>
  );
}

function Palette({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [input, setInput] = useState("");
  const [term, setTerm] = useState("");
  const [active, setActive] = useState(0);
  const q = useGlobalSearch(term);
  const hits = term.length >= 2 ? (q.data ?? []) : [];

  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => {
    const t = setTimeout(() => {
      const v = input.trim();
      setTerm(v.length >= 2 ? v : "");
      setActive(0);
    }, 250);
    return () => clearTimeout(t);
  }, [input]);

  const go = useCallback(
    (h: SearchHit) => {
      onClose();
      nav(hitPath(h));
    },
    [nav, onClose],
  );

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown" && hits.length) {
      e.preventDefault();
      setActive((i) => (i + 1) % hits.length);
    } else if (e.key === "ArrowUp" && hits.length) {
      e.preventDefault();
      setActive((i) => (i - 1 + hits.length) % hits.length);
    } else if (e.key === "Enter" && hits[active]) {
      e.preventDefault();
      go(hits[active]);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[10vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Глобальный поиск" className="w-full max-w-lg rounded-lg border border-border bg-surface p-3 text-fg shadow-lg" onKeyDown={onKeyDown}>
        <input
          ref={inputRef}
          role="combobox"
          aria-expanded={hits.length > 0}
          aria-controls="gs-list"
          aria-activedescendant={hits[active] ? `gs-${active}` : undefined}
          aria-label="Поиск клиентов и автомобилей"
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder="Клиент, телефон, госномер, VIN"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="min-h-10 w-full rounded border border-border bg-bg px-3 text-fg placeholder:text-muted"
        />
        <ul id="gs-list" role="listbox" aria-label="Результаты поиска" className="mt-2 max-h-[50vh] overflow-y-auto">
          {hits.map((h, i) => (
            <li
              key={`${h.type}-${h.id}`}
              id={`gs-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(h)}
              className={`flex cursor-pointer items-center justify-between gap-3 rounded px-3 py-2 text-sm ${i === active ? "bg-accent text-accent-fg" : ""}`}
            >
              <span className="min-w-0 truncate">
                <span className="font-medium">{h.title}</span>
                <span className="ml-2 opacity-80">{h.subtitle}</span>
              </span>
              <span className="shrink-0 text-xs opacity-80">{h.type === "client" ? "Клиент" : "Авто"}</span>
            </li>
          ))}
        </ul>
        <p role="status" className="px-1 pt-2 text-xs text-muted">
          {term.length < 2
            ? "Введите минимум 2 символа"
            : q.isError
              ? toAppError(q.error).message
              : q.isFetching
                ? "Поиск…"
                : hits.length === 0
                  ? "Ничего не найдено"
                  : "↑↓ — выбор, Enter — открыть, Esc — закрыть"}
        </p>
      </div>
    </div>
  );
}
