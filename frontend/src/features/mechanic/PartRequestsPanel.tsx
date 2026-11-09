import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { api } from "@/shared/api/client";
import { fieldText, toAppError } from "@/shared/api/errors";
import { PART_UNIT_LABELS, type Page, type Part, type PartUnit } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Dialog, Input, Textarea } from "@/shared/ui/ui";

import { mechanicErrorText, usePartRequestAction, usePartRequestSummary, usePartRequests } from "./api";
import { useDebounced } from "./time";
import { PART_REQUEST_LABELS, type PartRequestFull, type PartRequestStatus } from "./types";

const STEP = 50;
function unitLabel(u: string | null | undefined): string {
  return u ? (PART_UNIT_LABELS[u as PartUnit] ?? u) : "шт";
}
const TONE = { new: "warning", approved: "success", rejected: "danger", issued: "neutral" } as const;

function usePartSearch(search: string) {
  const s = useDebounced(search.trim());
  return useQuery({
    queryKey: ["part-requests", "parts", s],
    queryFn: () => api<Page<Part>>(`/parts?search=${encodeURIComponent(s)}&is_active=true&limit=8`),
    enabled: s.length >= 2,
  });
}

export interface PartRequestsPanelProps {
  /** Точка; пусто — все доступные. */
  locationId?: string;
  /** Заявки одного заказа (блок на карточке заказа). */
  orderId?: string;
  title?: string;
  /** Не показывать ничего, если заявок нет (блок в карточке заказа). */
  hideWhenEmpty?: boolean;
  /** Фильтр по статусу (на странице «Заявки механиков»). */
  withFilter?: boolean;
}

/**
 * MG-11 (часть): заявки механиков. Самостоятельный компонент: встраивается в `/part-requests`,
 * в экран склада (`/stock/requests`, модуль 8) и в карточку заказа (`orderId`).
 */
export function PartRequestsPanel({ locationId, orderId, title, hideWhenEmpty, withFilter = true }: PartRequestsPanelProps) {
  const [status, setStatus] = useState<"" | PartRequestStatus>("");
  const [limit, setLimit] = useState(STEP);
  const q = usePartRequests({ locationId, orderId, status, limit });
  const summary = usePartRequestSummary(locationId);
  const [reject, setReject] = useState<PartRequestFull | null>(null);
  const [issue, setIssue] = useState<PartRequestFull | null>(null);
  const act = usePartRequestAction();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const data = q.data;

  if (hideWhenEmpty && (!data || data.items.length === 0)) return null;

  function approve(r: PartRequestFull) {
    setError(null);
    act.mutate({ id: r.id, action: "approve", body: {} }, { onSuccess: () => toast.push("success", "Заявка одобрена"), onError: (e) => setError(mechanicErrorText(e)) });
  }

  return (
    <section className="space-y-3" aria-label={title ?? "Заявки механиков"}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {title ? <h2 className="text-base font-semibold">{title}</h2> : <span />}
        <div className="flex items-center gap-2">
          {!orderId && summary.data && (
            <>
              <Badge tone={summary.data.new > 0 ? "warning" : "neutral"}>Новые: {summary.data.new}</Badge>
              <Badge>Одобрены: {summary.data.approved}</Badge>
            </>
          )}
          {withFilter && !orderId && (
            <select
              aria-label="Статус заявок"
              value={status}
              onChange={(e) => { setStatus(e.target.value as "" | PartRequestStatus); setLimit(STEP); }}
              className="min-h-9 rounded border border-border bg-surface px-2 text-sm"
            >
              <option value="">Все статусы</option>
              {(Object.keys(PART_REQUEST_LABELS) as PartRequestStatus[]).map((s) => <option key={s} value={s}>{PART_REQUEST_LABELS[s]}</option>)}
            </select>
          )}
        </div>
      </div>

      {error && <Alert>{error}</Alert>}
      {q.isLoading && <p role="status" className="py-4 text-center text-sm text-muted">Загрузка…</p>}
      {q.isError && !data && (
        <div role="alert" className="space-y-2 text-center">
          <p className="text-sm text-muted">Не удалось загрузить</p>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      )}
      {data && data.items.length === 0 && <p className="py-6 text-center text-sm text-muted">Новых заявок нет</p>}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {data.items.map((r) => (
            <RequestRow key={r.id} r={r} busy={act.isPending} onApprove={approve} onReject={setReject} onIssue={setIssue} showOrder={!orderId} />
          ))}
        </ul>
      )}
      {data && data.total > data.items.length && <Button variant="secondary" onClick={() => setLimit((l) => l + STEP)}>Показать ещё</Button>}

      {reject && <RejectDialog r={reject} onClose={() => setReject(null)} />}
      {issue && <IssueDialog r={issue} onClose={() => setIssue(null)} />}
    </section>
  );
}

function RequestRow({
  r, busy, onApprove, onReject, onIssue, showOrder,
}: {
  r: PartRequestFull;
  busy: boolean;
  onApprove: (r: PartRequestFull) => void;
  onReject: (r: PartRequestFull) => void;
  onIssue: (r: PartRequestFull) => void;
  showOrder: boolean;
}) {
  const open = r.status === "new" || r.status === "approved";
  const stock = r.part?.in_stock;
  const short = stock != null && Number(stock) < Number(r.quantity);
  return (
    <li className="space-y-2 p-3" data-request={r.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm">
            {showOrder && (
              <Link to={`/orders/${encodeURIComponent(r.order.id)}`} className="font-medium underline">{r.order.number}</Link>
            )}
            {showOrder && " · "}
            {r.vehicle.make} {r.vehicle.model}{r.vehicle.plate_number ? `, ${r.vehicle.plate_number}` : ""}
          </div>
          <div className="text-base font-medium">{r.part?.name ?? r.description}</div>
          {r.part && r.description && r.description !== r.part.name && <div className="text-sm">{r.description}</div>}
          <div className="text-sm text-muted">
            {Number(r.quantity)} {unitLabel(r.part?.unit)}
            {r.part?.sku ? ` · ${r.part.sku}` : ""}
            {stock != null && <span className={short ? "text-danger" : undefined}> · остаток: {Number(stock)}</span>}
          </div>
          <div className="text-xs text-muted">{r.mechanic.full_name}{r.item_name ? ` · ${r.item_name}` : ""}</div>
          {r.status === "rejected" && r.reject_reason && <div className="text-sm text-danger">Причина: {r.reject_reason}</div>}
        </div>
        <Badge tone={TONE[r.status]}>{PART_REQUEST_LABELS[r.status]}</Badge>
      </div>
      {open && (
        <div className="flex flex-wrap gap-2">
          {r.status === "new" && <Button variant="secondary" disabled={busy} onClick={() => onApprove(r)}>Одобрить</Button>}
          <Button disabled={busy} onClick={() => onIssue(r)}>Выдать</Button>
          <Button variant="ghost" disabled={busy} onClick={() => onReject(r)}>Отклонить</Button>
        </div>
      )}
    </li>
  );
}

function RejectDialog({ r, onClose }: { r: PartRequestFull; onClose: () => void }) {
  const act = usePartRequestAction();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = reason.trim();
    if (!t) return setFieldErr("Укажите причину отказа (до 500 символов)");
    setFieldErr(undefined);
    setError(null);
    act.mutate(
      { id: r.id, action: "reject", body: { reason: t } },
      {
        onSuccess: () => { toast.push("success", "Заявка отклонена"); onClose(); },
        onError: (e2) => {
          const fe = fieldText(toAppError(e2), "reason", "Укажите причину отказа (до 500 символов)");
          if (fe) setFieldErr(fe);
          else setError(mechanicErrorText(e2));
        },
      },
    );
  }

  return (
    <Dialog open title="Отклонить заявку" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <p className="text-sm text-muted">{r.part?.name ?? r.description}, {Number(r.quantity)} · {r.mechanic.full_name}</p>
        <Textarea label="Причина отказа" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} error={fieldErr} />
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="danger" loading={act.isPending}>Отклонить</Button>
        </div>
      </form>
    </Dialog>
  );
}

function IssueDialog({ r, onClose }: { r: PartRequestFull; onClose: () => void }) {
  const me = useMe();
  const act = usePartRequestAction();
  const toast = useToast();
  const [qty, setQty] = useState(String(Number(r.quantity)));
  const [price, setPrice] = useState("");
  const [search, setSearch] = useState("");
  const [part, setPart] = useState<{ id: string; name: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const hits = usePartSearch(search);

  function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const q3 = parseDecimal(qty, 3);
    if (!q3 || Number(q3) <= 0) errs.quantity = "Количество: число больше 0, до трёх знаков после запятой";
    const p2 = price.trim() ? parseDecimal(price, 2) : undefined;
    if (price.trim() && !p2) errs.unit_price = "Цена: число не меньше 0, до двух знаков после запятой";
    if (!r.part && !part) errs.part_id = "Выберите запчасть из каталога";
    setErrors(errs);
    setError(null);
    if (Object.keys(errs).length) return;
    const body: Record<string, unknown> = { version: r.order.version, quantity: q3 };
    if (!r.part && part) body.part_id = part.id;
    if (p2) body.unit_price = p2;
    act.mutate(
      { id: r.id, action: "issue", body },
      {
        onSuccess: () => { toast.push("success", "Запчасть выдана и добавлена в заказ"); onClose(); },
        onError: (e2) => {
          const err = toAppError(e2);
          const f: Record<string, string> = {};
          if (err.fields.part_id) f.part_id = "Выберите запчасть из каталога";
          if (err.fields.quantity) f.quantity = "Количество: число больше 0, до трёх знаков после запятой";
          if (err.fields.unit_price) f.unit_price = "Цена: число не меньше 0, до двух знаков после запятой";
          setErrors(f);
          if (Object.keys(f).length === 0) setError(mechanicErrorText(e2));
        },
      },
    );
  }

  return (
    <Dialog open title="Выдать запчасть" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <p className="text-sm">
          <span className="font-medium">{r.part?.name ?? r.description}</span>
          <span className="text-muted"> · заказ {r.order.number}</span>
        </p>
        {!r.part && (
          <div className="space-y-2">
            {part ? (
              <div className="flex items-center justify-between gap-2 rounded border border-border p-2 text-sm">
                <span>{part.name}</span>
                <Button type="button" variant="ghost" onClick={() => setPart(null)}>Сменить</Button>
              </div>
            ) : (
              <>
                <Input label="Запчасть из каталога" value={search} onChange={(e) => setSearch(e.target.value)} error={errors.part_id} autoComplete="off" />
                {hits.data && hits.data.items.length > 0 && (
                  <ul className="divide-y divide-border rounded border border-border" aria-label="Результаты поиска">
                    {hits.data.items.map((p) => (
                      <li key={p.id}>
                        <button type="button" className="block w-full px-3 py-2 text-left text-sm hover:bg-border/50" onClick={() => { setPart({ id: p.id, name: p.name }); setSearch(""); }}>
                          {p.name} <span className="text-xs text-muted">{p.sku}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
        <Input label={`Количество, ${unitLabel(r.part?.unit)}`} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} error={errors.quantity} />
        {me.role === "director" && (
          <Input
            label="Цена за единицу (необязательно)"
            inputMode="decimal"
            value={price}
            placeholder={r.part ? r.part.sale_price : "по каталогу"}
            onChange={(e) => setPrice(e.target.value)}
            error={errors.unit_price}
          />
        )}
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={act.isPending}>Выдать</Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Блок «Заявки механиков по заказу» для вкладки «Запчасти» карточки заказа (MG-05). */
export function OrderPartRequests({ orderId }: { orderId: string }) {
  return <PartRequestsPanel orderId={orderId} title="Заявки механиков по заказу" hideWhenEmpty withFilter={false} />;
}
