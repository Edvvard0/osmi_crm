import clsx from "clsx";
import { type FormEvent, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { MoreHorizontal } from "lucide-react";

import { NotFoundPage } from "@/pages/ErrorPage";
import { fieldMessage, toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS } from "@/shared/api/types";
import { Modal } from "@/shared/ui/modal";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Textarea } from "@/shared/ui/ui";

import { useAddTaskComment, useFinishTask, useTask } from "./api";
import { formatClock, formatDateTime, formatNorm, taskSeconds, useNow, usePullToRefresh } from "./time";
import type { MechanicTaskDetail } from "./types";
import { BIG, LiveClock, LoadError, Plate, Section, Skeleton, StatusBadge, isNotFound, useTimerActions } from "./ui";

const HINT = "Заказ ещё не передан в работу";

/** M-02: карточка работы (+ M-03 — завершение). */
export function TaskPage() {
  const { itemId } = useParams();
  const q = useTask(itemId);
  const pulling = usePullToRefresh(() => void q.refetch());
  if (q.isLoading) return <Skeleton />;
  if (q.isError && isNotFound(q.error)) return <NotFoundPage />;
  if (q.isError || !q.data) return <LoadError onRetry={() => void q.refetch()} />;
  return (
    <>
      {pulling && <p role="status" className="mb-2 text-center text-sm text-muted">Обновляется…</p>}
      <TaskView task={q.data} receivedAt={q.dataUpdatedAt} />
    </>
  );
}

function TaskView({ task, receivedAt }: { task: MechanicTaskDetail; receivedAt: number }) {
  const actions = useTimerActions();
  const [menu, setMenu] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const commentRef = useRef<HTMLDivElement>(null);
  const href = `/tasks/${encodeURIComponent(task.item_id)}`;
  const { status, can_start: canStart } = task;
  const finishable = (status === "in_progress" || (status === "paused" && canStart)) && !actions.busy;

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <header className="space-y-1">
        <div className="flex items-start justify-between gap-2">
          <Plate task={task} className="text-2xl" />
          <div className="flex items-center gap-1">
            <Badge>{DEPARTMENT_LABELS[task.department]}</Badge>
            <div className="relative">
              <button
                type="button"
                aria-label="Ещё"
                aria-haspopup="menu"
                aria-expanded={menu}
                onClick={() => setMenu((v) => !v)}
                className="grid h-12 w-12 place-items-center rounded border border-border text-xl"
              >
                <MoreHorizontal size={22} aria-hidden="true" />
              </button>
              {menu && (
                <div role="menu" className="absolute right-0 z-10 mt-1 w-56 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
                  <Link role="menuitem" to={`${href}/part-request`} className="block px-4 py-4 text-base hover:bg-border/50">Нужна запчасть</Link>
                  <Link role="menuitem" to={`${href}/recommendation`} className="block px-4 py-4 text-base hover:bg-border/50">Рекомендация</Link>
                  <button
                    role="menuitem"
                    type="button"
                    className="block w-full px-4 py-4 text-left text-base hover:bg-border/50"
                    onClick={() => {
                      setMenu(false);
                      commentRef.current?.scrollIntoView?.({ block: "center" });
                      commentRef.current?.querySelector("textarea")?.focus();
                    }}
                  >
                    Комментарий
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="text-base">
          {task.vehicle.make} {task.vehicle.model}
          {task.vehicle.year ? `, ${task.vehicle.year}` : ""}
          {task.vehicle.color ? ` · ${task.vehicle.color}` : ""}
        </div>
        <div className="text-sm text-muted">
          Заказ {task.order_number}
          {task.mileage_in != null ? ` · пробег ${task.mileage_in.toLocaleString("ru-RU")} км` : ""}
          {task.planned_ready_at ? ` · срок ${formatDateTime(task.planned_ready_at)}` : ""}
        </div>
        {task.is_overdue && <Badge tone="danger">Просрочено</Badge>}
      </header>

      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="text-lg font-medium">{task.name}</div>
          <StatusBadge status={status} />
        </div>
        <div className="mt-2 flex items-baseline justify-between text-sm text-muted">
          <span>Норматив: {formatNorm(task.norm_hours)}</span>
          <LiveClock task={task} receivedAt={receivedAt} className="text-2xl font-semibold text-fg" />
        </div>
      </div>

      <Section title="Жалоба клиента">
        <p className="whitespace-pre-wrap text-base">{task.complaint || "—"}</p>
      </Section>
      <Section title="Состояние при приёме">
        <p className="whitespace-pre-wrap text-base">{task.intake_notes || "—"}</p>
      </Section>

      <Section title="Мои работы в этом заказе">
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {task.my_items.map((it) => (
            <li key={it.item_id} className={clsx("flex items-center justify-between gap-2 px-3 py-3", it.item_id === task.item_id && "bg-border/30")}>
              <div className="min-w-0">
                <div className="truncate text-base">{it.name}</div>
                <div className="text-xs text-muted">Норма {formatNorm(it.norm_hours)}</div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <StatusBadge status={it.status} />
                <LiveClock task={it} receivedAt={receivedAt} className="text-sm text-muted" />
              </div>
            </li>
          ))}
        </ul>
      </Section>

      <Comments task={task} inputRef={commentRef} />

      {/* Липкая панель действий */}
      <div className="sticky bottom-[4.5rem] -mx-4 border-t border-border bg-bg/95 p-3 backdrop-blur md:bottom-0 md:mx-0 md:rounded-lg md:border">
        {status === "done" ? (
          <p className="text-center text-sm text-muted">Работа выполнена {formatDateTime(task.finished_at)}</p>
        ) : (
          <div className="space-y-2">
            {!canStart && status !== "in_progress" && <p className="text-center text-sm text-muted">{HINT}</p>}
            <div className="flex gap-2">
              {status === "in_progress" && (
                <Button className={clsx(BIG, "flex-1")} variant="secondary" disabled={actions.busy || !actions.online} onClick={() => void actions.pause(task)}>
                  Пауза
                </Button>
              )}
              {status !== "in_progress" && canStart && (
                <Button className={clsx(BIG, "flex-1")} disabled={actions.busy || !actions.online} onClick={() => void actions.start(task)}>
                  {status === "paused" ? "Продолжить" : "Начать"}
                </Button>
              )}
              {finishable && (
                <Button className={clsx(BIG, "flex-1")} variant={status === "in_progress" ? "primary" : "secondary"} disabled={!actions.online} onClick={() => setFinishing(true)}>
                  Завершить
                </Button>
              )}
            </div>
          </div>
        )}
      </div>

      {actions.dialog}
      {finishing && <FinishSheet task={task} receivedAt={receivedAt} onClose={() => setFinishing(false)} />}
    </div>
  );
}

function Comments({ task, inputRef }: { task: MechanicTaskDetail; inputRef: React.RefObject<HTMLDivElement> }) {
  const add = useAddTaskComment(task.item_id);
  const [text, setText] = useState("");
  const err = add.error ? toAppError(add.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    add.mutate(t, { onSuccess: () => setText("") });
  }

  return (
    <Section title="Комментарии">
      {task.comments.length === 0 ? (
        <p className="text-sm text-muted">Комментариев пока нет</p>
      ) : (
        <ul className="space-y-2">
          {task.comments.map((c) => (
            <li key={c.id} className="rounded-lg border border-border bg-surface px-3 py-2">
              <div className="flex justify-between gap-2 text-xs text-muted">
                <span>{c.author.full_name}</span>
                <span>{formatDateTime(c.created_at)}</span>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-base">{c.text}</p>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="space-y-2">
        <div ref={inputRef}>
          <Textarea label="Новый комментарий" value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} error={err ? (fieldMessage(err, "text") ?? err.message) : undefined} />
        </div>
        <Button type="submit" className={BIG} variant="secondary" loading={add.isPending} disabled={!text.trim()}>Добавить</Button>
      </form>
    </Section>
  );
}

/** M-03: завершение работы (bottom sheet). */
function FinishSheet({ task, receivedAt, onClose }: { task: MechanicTaskDetail; receivedAt: number; onClose: () => void }) {
  const nav = useNavigate();
  const toast = useToast();
  const finish = useFinishTask();
  const [comment, setComment] = useState("");
  const running = !!task.running_since;
  const now = useNow(running);
  const err = finish.error ? toAppError(finish.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    finish.mutate(
      { itemId: task.item_id, comment: comment.trim() || undefined },
      {
        onSuccess: (r) => {
          toast.push("success", r.order_auto_moved ? "Все работы заказа выполнены" : "Работа завершена");
          nav("/");
        },
      },
    );
  }

  return (
    <Modal title="Завершение работы" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="text-center">
          <div className="text-sm text-muted">Фактическое время</div>
          <div className="text-4xl font-semibold tabular-nums" aria-label="Фактическое время">{formatClock(taskSeconds(task, receivedAt, now))}</div>
          <div className="mt-1 text-sm text-muted">{task.name}</div>
        </div>
        <Textarea label="Комментарий (необязательно)" value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} error={err ? fieldMessage(err, "comment") : undefined} />
        {err && !err.fields.comment && <Alert>{err.message}</Alert>}
        <Button type="submit" className={clsx(BIG, "w-full")} loading={finish.isPending}>Завершить работу</Button>
      </form>
    </Modal>
  );
}
