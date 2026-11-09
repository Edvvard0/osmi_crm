import clsx from "clsx";
import { useState } from "react";

import { readPref, writePref } from "@/shared/lib/storage";

import { useTasks } from "./api";
import { usePullToRefresh } from "./time";
import type { TaskScope } from "./types";
import { LoadError, Skeleton, TaskCard, useTimerActions } from "./ui";

const SCOPE_KEY = "crm.mechanic.scope";

/** M-01: «Мои задачи» — главный экран механика (маршрут `/`). */
export function MechanicTasksPage() {
  const [scope, setScope] = useState<TaskScope>(() => (readPref(SCOPE_KEY) === "open" ? "open" : "today"));
  const q = useTasks(scope);
  const actions = useTimerActions();
  const pulling = usePullToRefresh(() => void q.refetch());

  function pick(s: TaskScope) {
    setScope(s);
    writePref(SCOPE_KEY, s);
  }

  const data = q.data;
  const receivedAt = q.dataUpdatedAt;
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <h1 className="text-xl font-semibold">Мои задачи</h1>
      {pulling && <p role="status" className="text-center text-sm text-muted">Обновляется…</p>}

      {data?.active && <TaskCard task={data.active} receivedAt={receivedAt} actions={actions} highlight />}

      <div role="group" aria-label="Период" className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-surface p-1">
        {(["today", "open"] as const).map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={scope === s}
            onClick={() => pick(s)}
            className={clsx("min-h-12 rounded text-base font-medium", scope === s ? "bg-accent text-accent-fg" : "text-muted hover:bg-border/50")}
          >
            {s === "today" ? "Сегодня" : "Все открытые"}
          </button>
        ))}
      </div>

      {q.isLoading && <Skeleton />}
      {q.isError && !data && <LoadError onRetry={() => void q.refetch()} />}
      {data && data.items.length === 0 && !data.active && (
        <p className="py-8 text-center text-sm text-muted">{scope === "today" ? "На сегодня задач нет" : "Открытых задач нет"}</p>
      )}
      {data && (
        <div className="space-y-3">
          {data.items.map((t) => (
            <TaskCard key={t.item_id} task={t} receivedAt={receivedAt} actions={actions} />
          ))}
        </div>
      )}
      {actions.dialog}
    </div>
  );
}
