import { useState } from "react";

import { hasUnsavedForm, installDirtyFormTracking } from "@/shared/pwa/dirtyForms";
import { applyUpdate, dismissUpdate, useUpdateState } from "@/shared/pwa/updater";
import { Button } from "@/shared/ui/ui";

installDirtyFormTracking();

/** C-05: плашка «Доступна новая версия» с кнопками «Обновить» / «Позже». */
export function UpdatePrompt() {
  const { needRefresh, dismissed } = useUpdateState();
  const [confirm, setConfirm] = useState(false);
  if (!needRefresh || dismissed) return null;

  const update = () => {
    // Несохранённый ввод пропадёт при перезагрузке — сначала спрашиваем.
    if (!confirm && hasUnsavedForm()) {
      setConfirm(true);
      return;
    }
    void applyUpdate();
  };

  return (
    <div role="status" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-border bg-surface px-4 py-2 text-sm">
      <span>{confirm ? "Несохранённые данные в форме будут потеряны. Обновить?" : "Доступна новая версия"}</span>
      <span className="flex gap-2">
        <Button className="min-h-11 px-3 md:min-h-9" onClick={update} offlineSafe>
          {confirm ? "Всё равно обновить" : "Обновить"}
        </Button>
        <Button
          variant="secondary"
          className="min-h-11 px-3 md:min-h-9"
          onClick={() => {
            if (confirm) setConfirm(false);
            else dismissUpdate();
          }}
          offlineSafe
        >
          {confirm ? "Отмена" : "Позже"}
        </Button>
      </span>
    </div>
  );
}
