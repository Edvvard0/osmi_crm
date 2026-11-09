import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { isOffline, resetScreenData, useConnectivity } from "@/shared/lib/connectivity";

export function formatHm(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * C-04: баннер «Нет соединения». Виден на всех экранах, включая /login.
 * Офлайн — `navigator.onLine === false` или сетевая ошибка запроса / ответ из офлайн-кэша; не показывается при 502/503/504.
 */
export function OfflineBanner() {
  const c = useConnectivity();
  const { pathname } = useLocation();
  // «Данные на HH:MM» — по запросам текущего экрана.
  useEffect(() => resetScreenData(), [pathname]);
  if (!isOffline(c)) return null;
  return (
    <div role="alert" className="border-b border-warning/40 bg-warning/15 px-4 py-2 text-center text-sm text-fg">
      {c.dataAt ? `Нет соединения. Показаны данные на ${formatHm(c.dataAt)}` : "Нет соединения"}
    </div>
  );
}
