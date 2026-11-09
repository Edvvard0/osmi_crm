import clsx from "clsx";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PART_UNIT_LABELS, type PartUnit } from "@/shared/api/types";
import { Badge, Button } from "@/shared/ui/ui";

import { useMyPartRequests } from "./api";
import { formatDateTime, usePullToRefresh } from "./time";
import { PART_REQUEST_LABELS, type PartRequestStatus } from "./types";
import { BIG, LoadError, Skeleton } from "./ui";

const STEP = 30;
const FILTERS: Array<{ v: "" | PartRequestStatus; label: string }> = [
  { v: "", label: "Все" },
  { v: "new", label: "Новые" },
  { v: "approved", label: "Одобрены" },
  { v: "rejected", label: "Отклонены" },
  { v: "issued", label: "Выданы" },
];
const TONE = { new: "neutral", approved: "success", rejected: "danger", issued: "success" } as const;

/** M-05: мои заявки на запчасти. */
export function MyRequestsPage() {
  const [status, setStatus] = useState<"" | PartRequestStatus>("");
  const [limit, setLimit] = useState(STEP);
  const q = useMyPartRequests(status, limit);
  const pulling = usePullToRefresh(() => void q.refetch());
  const data = q.data;

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <h1 className="text-xl font-semibold">Мои заявки</h1>
      {pulling && <p role="status" className="text-center text-sm text-muted">Обновляется…</p>}
      <div role="group" aria-label="Статус" className="flex gap-1 overflow-x-auto">
        {FILTERS.map((f) => (
          <button
            key={f.v}
            type="button"
            aria-pressed={status === f.v}
            onClick={() => { setStatus(f.v); setLimit(STEP); }}
            className={clsx("min-h-11 whitespace-nowrap rounded border px-3 text-sm", status === f.v ? "border-accent bg-accent text-accent-fg" : "border-border text-muted")}
          >
            {f.label}
          </button>
        ))}
      </div>
      {q.isLoading && <Skeleton />}
      {q.isError && !data && <LoadError onRetry={() => void q.refetch()} />}
      {data && data.items.length === 0 && <p className="py-8 text-center text-sm text-muted">Заявок пока нет</p>}
      {data && (
        <ul className="space-y-3">
          {data.items.map((r) => (
            <li key={r.id} className="space-y-1 rounded-lg border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 text-base font-medium">{r.part?.name ?? r.description}</div>
                <Badge tone={TONE[r.status]}>{PART_REQUEST_LABELS[r.status]}</Badge>
              </div>
              {r.part && r.description && r.description !== r.part.name && <p className="text-sm">{r.description}</p>}
              <div className="text-sm text-muted">
                {Number(r.quantity)} {r.unit ? (PART_UNIT_LABELS[r.unit as PartUnit] ?? r.unit) : "шт"} · заказ {r.order_number}
                {r.item_name ? ` · ${r.item_name}` : ""}
              </div>
              <div className="text-xs text-muted">{formatDateTime(r.created_at)}</div>
              {r.status === "rejected" && r.reject_reason && <p className="text-sm text-danger">Причина: {r.reject_reason}</p>}
              {r.item_id && <Link to={`/tasks/${encodeURIComponent(r.item_id)}`} className="inline-block text-sm underline">К работе</Link>}
            </li>
          ))}
        </ul>
      )}
      {data && data.total > data.items.length && (
        <Button className={clsx(BIG, "w-full")} variant="secondary" onClick={() => setLimit((l) => l + STEP)}>Показать ещё</Button>
      )}
    </div>
  );
}
