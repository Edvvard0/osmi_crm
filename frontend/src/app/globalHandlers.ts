import { toast } from "@/shared/ui/toast";
import { reportClientError } from "@/shared/lib/reporter";

/** window.onerror и unhandledrejection: лог на сервер + нейтральный toast. */
export function installGlobalHandlers(): () => void {
  const onError = (ev: ErrorEvent) => {
    reportClientError("onerror", ev.error ?? ev.message);
    toast.error(new Error("unknown"));
  };
  const onRejection = (ev: PromiseRejectionEvent) => {
    reportClientError("unhandledrejection", ev.reason);
    toast.error(ev.reason);
    ev.preventDefault();
  };
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
