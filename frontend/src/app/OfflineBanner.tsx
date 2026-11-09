import { useEffect, useState } from "react";

/** C-04: баннер «Нет соединения» — по событиям браузера. */
export function OfflineBanner() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  if (online) return null;
  return (
    <div role="alert" className="bg-warning/15 px-4 py-2 text-center text-sm text-warning">
      Нет соединения с сервером
    </div>
  );
}
