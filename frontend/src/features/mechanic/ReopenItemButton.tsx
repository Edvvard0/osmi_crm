import { useState } from "react";

import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Dialog } from "@/shared/ui/ui";

import { mechanicErrorText, useReopenItem } from "./api";

/**
 * Кнопка «Вернуть в работу» для выполненной работы (done) на карточке заказа (MG-05).
 * `version` — текущая версия заказа. Ответ сервера кладёт свежий заказ в кэш ["order", orderId].
 */
export function ReopenItemButton({ orderId, itemId, version }: { orderId: string; itemId: string; version: number }) {
  const reopen = useReopenItem(orderId);
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function run() {
    setError(null);
    reopen.mutate(
      { itemId, version },
      {
        onSuccess: () => { toast.push("success", "Работа возвращена в исполнение"); setConfirm(false); },
        onError: (e) => setError(mechanicErrorText(e)),
      },
    );
  }

  return (
    <>
      <Button variant="ghost" onClick={() => { setError(null); setConfirm(true); }}>Вернуть в работу</Button>
      <Dialog open={confirm} title="Вернуть работу в исполнение?" onClose={() => setConfirm(false)}>
        <p className="text-sm text-muted">Работа снова станет доступной механику; таймер продолжится с накопленного времени.</p>
        {error && <div className="mt-3"><Alert>{error}</Alert></div>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(false)}>Отмена</Button>
          <Button loading={reopen.isPending} onClick={run}>Вернуть</Button>
        </div>
      </Dialog>
    </>
  );
}
