import clsx from "clsx";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import type { ItemStatus } from "@/features/orders/types";
import { useToast } from "@/shared/ui/toast";
import { AppError, toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS } from "@/shared/api/types";
import { Badge, Button, Dialog } from "@/shared/ui/ui";

import { usePauseTask, useStartTask } from "./api";
import { formatClock, formatNorm, taskSeconds, useNow, useOnline } from "./time";
import type { MechanicTask, TaskItemBrief } from "./types";

export const ITEM_LABELS: Record<ItemStatus, string> = {
  pending: "Ожидает",
  in_progress: "В работе",
  paused: "Пауза",
  done: "Готово",
  cancelled: "Отменена",
};

/** Кнопка механика: от 56 px (экраны на телефоне). */
export const BIG = "min-h-14 text-base";

export function StatusBadge({ status }: { status: ItemStatus }) {
  return <Badge tone={status === "in_progress" ? "success" : status === "paused" ? "warning" : "neutral"}>{ITEM_LABELS[status]}</Badge>;
}

export function Plate({ task, className }: { task: Pick<MechanicTask, "vehicle">; className?: string }) {
  return <span className={clsx("font-mono text-xl font-semibold tracking-wide", className)}>{task.vehicle.plate_number ?? "без номера"}</span>;
}

/** Живой таймер: `receivedAt` — момент получения ответа (dataUpdatedAt запроса). */
export function LiveClock({ task, receivedAt, className }: { task: Pick<TaskItemBrief, "worked_seconds" | "running_since">; receivedAt: number; className?: string }) {
  const now = useNow(!!task.running_since);
  return (
    <span className={clsx("tabular-nums", className)} aria-label="Время работы">
      {formatClock(taskSeconds(task, receivedAt, now))}
    </span>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Загрузка" className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-24 animate-pulse rounded-lg border border-border bg-border/30" />
      ))}
    </div>
  );
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="space-y-3 rounded-lg border border-border bg-surface p-4 text-center">
      <p className="text-sm text-muted">Не удалось загрузить</p>
      <Button variant="secondary" onClick={onRetry}>Повторить</Button>
    </div>
  );
}

/**
 * Старт и пауза с обработкой `another_task_active`: диалог «Поставить на паузу и начать эту».
 * Возвращает действия и готовый узел диалога, который нужно вывести на странице.
 */
export function useTimerActions() {
  const toast = useToast();
  const start = useStartTask();
  const pause = usePauseTask();
  const online = useOnline();
  const [conflict, setConflict] = useState<{ task: MechanicTask; active: { order_number: string; item_name: string } } | null>(null);

  const fail = (e: unknown) => toast.error(e);
  const doStart = (task: MechanicTask, pauseActive = false) =>
    start.mutateAsync({ itemId: task.item_id, pauseActive }).then(
      () => setConflict(null),
      (e: unknown) => {
        const err = toAppError(e);
        if (err.code === "another_task_active" && !pauseActive) {
          setConflict({ task, active: { order_number: err.details.order_number ?? "", item_name: err.details.item_name ?? "" } });
        } else {
          setConflict(null);
          fail(e);
        }
      },
    );
  const doPause = (task: Pick<MechanicTask, "item_id">) => pause.mutateAsync(task.item_id).then(() => undefined, fail);

  const dialog = (
    <Dialog open={!!conflict} title="Другая работа уже идёт" onClose={() => setConflict(null)}>
      {conflict && (
        <div className="space-y-4">
          <p className="text-sm">
            Сейчас выполняется «{conflict.active.item_name || "другая работа"}»
            {conflict.active.order_number ? ` (заказ ${conflict.active.order_number})` : ""}. Поставить её на паузу и начать эту?
          </p>
          <div className="flex flex-col gap-2">
            <Button className={BIG} loading={start.isPending} disabled={!online} onClick={() => void doStart(conflict.task, true)}>
              Поставить на паузу и начать эту
            </Button>
            <Button className={BIG} variant="secondary" onClick={() => setConflict(null)}>Отмена</Button>
          </div>
        </div>
      )}
    </Dialog>
  );

  return { start: doStart, pause: doPause, busy: start.isPending || pause.isPending, online, dialog };
}

export function TaskCard({
  task,
  receivedAt,
  actions,
  highlight,
}: {
  task: MechanicTask;
  receivedAt: number;
  actions: ReturnType<typeof useTimerActions>;
  highlight?: boolean;
}) {
  const running = task.status === "in_progress";
  return (
    <article className={clsx("rounded-lg border bg-surface p-4", highlight ? "border-accent" : "border-border")} data-task={task.item_id}>
      <Link to={`/tasks/${encodeURIComponent(task.item_id)}`} className="block space-y-1">
        <div className="flex items-start justify-between gap-2">
          <Plate task={task} />
          <div className="flex flex-wrap justify-end gap-1">
            <Badge>{DEPARTMENT_LABELS[task.department]}</Badge>
            <StatusBadge status={task.status} />
            {task.is_overdue && <Badge tone="danger">Просрочено</Badge>}
          </div>
        </div>
        <div className="text-sm text-muted">{task.vehicle.make} {task.vehicle.model} · {task.order_number}</div>
        <div className="text-base font-medium">{task.name}</div>
        <div className="flex items-center justify-between text-sm text-muted">
          <span>Норматив: {formatNorm(task.norm_hours)}</span>
          {(running || task.worked_seconds > 0) && <LiveClock task={task} receivedAt={receivedAt} className={clsx(running && "text-lg font-semibold text-fg")} />}
        </div>
      </Link>
      {running && (
        <Button className={clsx(BIG, "mt-3 w-full")} variant="secondary" disabled={actions.busy || !actions.online} onClick={() => void actions.pause(task)}>
          Пауза
        </Button>
      )}
      {!running && task.can_start && (
        <Button className={clsx(BIG, "mt-3 w-full")} disabled={actions.busy || !actions.online} onClick={() => void actions.start(task)}>
          {task.status === "paused" ? "Продолжить" : "Начать"}
        </Button>
      )}
    </article>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium uppercase tracking-wide text-muted">{title}</h2>
      {children}
    </section>
  );
}

export function isNotFound(e: unknown): boolean {
  return e instanceof AppError && e.status === 404;
}
