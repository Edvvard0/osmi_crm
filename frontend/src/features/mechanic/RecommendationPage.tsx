import clsx from "clsx";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { NotFoundPage } from "@/pages/ErrorPage";
import { fieldMessage, toAppError } from "@/shared/api/errors";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Textarea } from "@/shared/ui/ui";

import { useCreateMechanicRecommendation, useTask } from "./api";
import { useOnline } from "./time";
import { PRIORITY_LABELS, type Priority } from "./types";
import { BIG, LoadError, Skeleton, isNotFound } from "./ui";

/** M-06: рекомендация по авто. */
export function RecommendationPage() {
  const { itemId = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const online = useOnline();
  const task = useTask(itemId);
  const create = useCreateMechanicRecommendation();
  const [text, setText] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const err = create.error ? toAppError(create.error) : null;

  if (task.isLoading) return <Skeleton rows={2} />;
  if (task.isError && isNotFound(task.error)) return <NotFoundPage />;
  if (task.isError || !task.data) return <LoadError onRetry={() => void task.refetch()} />;

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    create.mutate(
      { item_id: itemId, text: t, priority },
      {
        onSuccess: () => {
          toast.push("success", "Рекомендация сохранена");
          nav(`/tasks/${encodeURIComponent(itemId)}`);
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-xl space-y-5" noValidate>
      <div>
        <Link to={`/tasks/${encodeURIComponent(itemId)}`} className="text-sm text-muted">← К работе</Link>
        <h1 className="mt-1 text-xl font-semibold">Рекомендация</h1>
        <p className="text-sm text-muted">{task.data.vehicle.make} {task.data.vehicle.model} · {task.data.vehicle.plate_number ?? "без номера"}</p>
      </div>
      <Textarea
        label="Что рекомендуете"
        rows={5}
        value={text}
        maxLength={1000}
        onChange={(e) => setText(e.target.value)}
        error={err?.fields.text ? "Рекомендация: от 1 до 1000 символов" : undefined}
      />
      <fieldset>
        <legend className="mb-1 text-sm text-muted">Приоритет</legend>
        <div role="radiogroup" aria-label="Приоритет" className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-surface p-1">
          {(["low", "medium", "high"] as const).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={priority === p}
              onClick={() => setPriority(p)}
              className={clsx("min-h-12 rounded text-base font-medium", priority === p ? "bg-accent text-accent-fg" : "text-muted hover:bg-border/50")}
            >
              {PRIORITY_LABELS[p]}
            </button>
          ))}
        </div>
        {err?.fields.priority && <p role="alert" className="mt-1 text-xs text-danger">{fieldMessage(err, "priority")}</p>}
      </fieldset>
      <p className="text-sm text-muted">Менеджер увидит при следующем визите</p>
      {err && !err.fields.text && !err.fields.priority && <Alert>{err.message}</Alert>}
      <Button type="submit" className={clsx(BIG, "w-full")} loading={create.isPending} disabled={!online || !text.trim()}>Сохранить</Button>
    </form>
  );
}
