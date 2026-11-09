import { useEffect, useState } from "react";

import type { MechanicTask, TaskItemBrief } from "./types";

/**
 * Секунды работы по позиции. `worked_seconds` уже включает открытый интервал на момент ответа,
 * поэтому к нему добавляется только время, прошедшее с получения ответа (это то же, что
 * Date.now() + offset − server_time, но без зависимости от часов телефона).
 */
export function taskSeconds(t: Pick<MechanicTask | TaskItemBrief, "worked_seconds" | "running_since">, receivedAt: number, now: number): number {
  if (!t.running_since) return t.worked_seconds;
  return t.worked_seconds + Math.max(0, Math.floor((now - receivedAt) / 1000));
}

/** 3725 → "1:02:05" */
export function formatClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** "1.50" → "1,5 ч" (нормочасы всей строки). */
export function formatNorm(v: string): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${String(Math.round(n * 100) / 100).replace(".", ",")} ч`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Тикает раз в секунду, пока `on`; иначе возвращает последнее значение. */
export function useNow(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [on]);
  return now;
}

export function useOnline(): boolean {
  const [on, setOn] = useState(() => navigator.onLine);
  useEffect(() => {
    const up = () => setOn(true);
    const down = () => setOn(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return on;
}

/** Жест «потянуть вниз» от верха страницы → onRefresh. */
export function usePullToRefresh(onRefresh: () => void): boolean {
  const [pulling, setPulling] = useState(false);
  useEffect(() => {
    let startY: number | null = null;
    let dy = 0;
    const onStart = (e: TouchEvent) => {
      const top = document.querySelector("main")?.scrollTop ?? 0;
      startY = top <= 0 ? e.touches[0].clientY : null;
      dy = 0;
    };
    const onMove = (e: TouchEvent) => {
      if (startY !== null) dy = e.touches[0].clientY - startY;
    };
    const onEnd = () => {
      if (startY !== null && dy > 90) {
        setPulling(true);
        onRefresh();
        setTimeout(() => setPulling(false), 800);
      }
      startY = null;
      dy = 0;
    };
    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: true });
    document.addEventListener("touchend", onEnd);
    return () => {
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
    };
  }, [onRefresh]);
  return pulling;
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}
