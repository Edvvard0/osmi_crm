import clsx from "clsx";
import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Minus, Plus } from "lucide-react";

import { NotFoundPage } from "@/pages/ErrorPage";
import { fieldMessage, fieldText, toAppError } from "@/shared/api/errors";
import { PART_UNIT_LABELS } from "@/shared/api/types";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Input, Textarea } from "@/shared/ui/ui";

import { useCreatePartRequest, useMechanicParts, useTask } from "./api";
import { useDebounced, useOnline } from "./time";
import type { PartHit } from "./types";
import { BIG, LoadError, Skeleton, isNotFound } from "./ui";

const MAX_QTY = 999;

/** M-04: заявка на запчасть. Поиск по справочнику (без цен) или свободный текст. */
export function PartRequestPage() {
  const { itemId = "" } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const online = useOnline();
  const task = useTask(itemId);
  const create = useCreatePartRequest();
  const [search, setSearch] = useState("");
  const [part, setPart] = useState<PartHit | null>(null);
  const [description, setDescription] = useState("");
  const [qty, setQty] = useState(1);
  const [local, setLocal] = useState<string | null>(null);
  const hits = useMechanicParts(useDebounced(search));
  const err = create.error ? toAppError(create.error) : null;

  if (task.isLoading) return <Skeleton rows={2} />;
  if (task.isError && isNotFound(task.error)) return <NotFoundPage />;
  if (task.isError || !task.data) return <LoadError onRetry={() => void task.refetch()} />;

  function submit(e: FormEvent) {
    e.preventDefault();
    const d = description.trim();
    if (!part && !d) {
      setLocal("Выберите запчасть из справочника или опишите, что нужно");
      return;
    }
    setLocal(null);
    create.mutate(
      { item_id: itemId, part_id: part?.id, description: d || undefined, quantity: qty.toFixed(3) },
      {
        onSuccess: () => {
          toast.push("success", "Заявка отправлена");
          nav(`/tasks/${encodeURIComponent(itemId)}`);
        },
      },
    );
  }

  const descError = local ?? fieldText(err, "description", "Укажите запчасть или опишите, что нужно (до 500 символов)");
  const otherError = err && !err.fields.description && !err.fields.quantity && !err.fields.part_id ? err.message : undefined;

  return (
    <form onSubmit={submit} className="mx-auto max-w-xl space-y-5" noValidate>
      <div>
        <Link to={`/tasks/${encodeURIComponent(itemId)}`} className="inline-flex items-center gap-1 text-sm text-muted"><ArrowLeft aria-hidden="true" className="size-4" />К работе</Link>
        <h1 className="mt-1 text-xl font-semibold">Нужна запчасть</h1>
        <p className="text-sm text-muted">{task.data.vehicle.plate_number ?? "без номера"} · {task.data.name}</p>
      </div>

      {part ? (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3">
          <div className="min-w-0">
            <div className="truncate text-base font-medium">{part.name}</div>
            <div className="text-xs text-muted">{part.sku}{part.brand ? ` · ${part.brand}` : ""}</div>
          </div>
          <Button type="button" variant="secondary" onClick={() => setPart(null)}>Сменить</Button>
        </div>
      ) : (
        <div className="space-y-2">
          <Input label="Поиск в справочнике" className="min-h-12 text-base" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Название или артикул" autoComplete="off" />
          {search.trim().length >= 2 && hits.isLoading && <p className="text-sm text-muted">Поиск…</p>}
          {hits.data && hits.data.length === 0 && <p className="text-sm text-muted">Ничего не найдено — опишите запчасть текстом ниже</p>}
          {hits.data && hits.data.length > 0 && (
            <ul className="divide-y divide-border rounded-lg border border-border bg-surface" aria-label="Результаты поиска">
              {hits.data.map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => { setPart(h); setSearch(""); }} className="block min-h-14 w-full px-3 py-2 text-left hover:bg-border/50">
                    <span className="block text-base">{h.name}</span>
                    <span className="block text-xs text-muted">{h.sku}{h.brand ? ` · ${h.brand}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Textarea
        label={part ? "Комментарий" : "Что нужно (если нет в справочнике)"}
        value={description}
        maxLength={500}
        onChange={(e) => setDescription(e.target.value)}
        error={descError}
      />

      <div>
        <div className="mb-1 text-sm text-muted">Количество{part ? `, ${PART_UNIT_LABELS[part.unit as keyof typeof PART_UNIT_LABELS] ?? part.unit}` : ""}</div>
        <div className="flex items-center gap-3">
          <button type="button" aria-label="Меньше" disabled={qty <= 1} onClick={() => setQty((q) => Math.max(1, q - 1))} className={clsx("grid h-14 w-14 place-items-center rounded border border-border disabled:opacity-40")}><Minus size={22} aria-hidden="true" /></button>
          <output aria-label="Количество" className="min-w-12 text-center text-2xl font-semibold tabular-nums">{qty}</output>
          <button type="button" aria-label="Больше" disabled={qty >= MAX_QTY} onClick={() => setQty((q) => Math.min(MAX_QTY, q + 1))} className="grid h-14 w-14 place-items-center rounded border border-border disabled:opacity-40"><Plus size={22} aria-hidden="true" /></button>
        </div>
        {err?.fields.quantity && <p role="alert" className="mt-1 text-xs text-danger">{fieldMessage(err, "quantity")}</p>}
        {err?.fields.part_id && <p role="alert" className="mt-1 text-xs text-danger">{fieldMessage(err, "part_id")}</p>}
      </div>

      {otherError && <Alert>{otherError}</Alert>}
      <Button type="submit" className={clsx(BIG, "w-full")} loading={create.isPending} disabled={!online}>Отправить</Button>
    </form>
  );
}
