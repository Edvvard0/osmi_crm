import { useState } from "react";
import { Link } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { ResponsiveList, Pager } from "@/pages/catalog/common";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Input, Loading, Select, Textarea } from "@/shared/ui/ui";

import { STOCK_PAGE_SIZE, type MovementFilters, useMovements, useReverse } from "./api";
import { PartPicker } from "./components";
import { fmtDateTime, fmtQty, fmtSignedQty, unitLabel } from "./format";
import { MOVEMENT_LABELS, type StockMovement, type StockMovementType } from "./types";

const REVERSIBLE: StockMovementType[] = ["receipt", "write_off", "adjustment"];
const WEEK_MS = 7 * 24 * 3600 * 1000;

export function ReverseModal({ movement, onClose }: { movement: StockMovement; onClose: () => void }) {
  const m = useReverse(movement.id);
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [le, setLe] = useState<string | undefined>();
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const r = reason.trim();
    if (r.length < 3 || r.length > 500) return setLe("Причина: от 3 до 500 символов");
    setLe(undefined);
    m.mutate({ reason: r }, { onSuccess: () => { toast.push("success", "Сторно выполнено"); onClose(); } });
  }

  return (
    <Modal title="Сторно движения" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <p className="text-sm text-muted">
          {MOVEMENT_LABELS[movement.movement_type]}: {movement.part.name}, {fmtSignedQty(movement.quantity)} {unitLabel(movement.part.unit)}
        </p>
        <Textarea id="reverse-reason" label="Причина" value={reason} onChange={(e) => setReason(e.target.value)} error={le ?? fieldMessage(err, "reason")} />
        {err && err.code !== "validation_error" && <Alert>{err.message}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={m.isPending}>Сторнировать</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Лента движений. fixedPartId — карточка позиции (без фильтра по запчасти). */
export function MovementsView({ locationId, fixedPartId }: { locationId: string; fixedPartId?: string }) {
  const me = useMe();
  const [type, setType] = useState<StockMovementType | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [part, setPart] = useState<{ id: string; name: string } | null>(null);
  const [offset, setOffset] = useState(0);
  const [reverse, setReverse] = useState<StockMovement | null>(null);
  const filters: MovementFilters = { location_id: locationId, part_id: fixedPartId ?? part?.id, movement_type: type, date_from: from, date_to: to };
  const q = useMovements(filters, offset);
  const items = q.data?.items ?? [];
  const err = q.error ? toAppError(q.error) : null;
  const emptyText = fixedPartId ? "Движений по позиции нет" : "Движений нет";

  const canReverse = (m: StockMovement) =>
    REVERSIBLE.includes(m.movement_type) &&
    !m.reversed &&
    m.related_movement_id === null &&
    (me.role === "director" || Date.now() - new Date(m.created_at).getTime() <= WEEK_MS);

  const orderLink = (m: StockMovement) =>
    m.work_order ? <Link to={`/orders/${m.work_order.id}`} className="underline">{m.work_order.number}</Link> : null;

  const reset = <T,>(fn: (v: T) => void) => (v: T) => { fn(v); setOffset(0); };

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Select id="mv-type" label="Тип" value={type} onChange={(e) => reset(setType)(e.target.value as StockMovementType | "")}>
          <option value="">Все типы</option>
          {(Object.keys(MOVEMENT_LABELS) as StockMovementType[]).map((t) => (
            <option key={t} value={t}>{MOVEMENT_LABELS[t]}</option>
          ))}
        </Select>
        <Input id="mv-from" label="С" type="date" value={from} onChange={(e) => reset(setFrom)(e.target.value)} />
        <Input id="mv-to" label="По" type="date" value={to} onChange={(e) => reset(setTo)(e.target.value)} error={fieldMessage(err, "date_to") ?? fieldMessage(err, "date_from")} />
        {!fixedPartId && (
          <div>
            {part ? (
              <div className="text-sm">
                <span className="mb-1 block text-muted">Запчасть</span>
                <span className="flex min-h-10 items-center gap-2">
                  <Badge>{part.name}</Badge>
                  <button type="button" className="text-muted underline" onClick={() => { setPart(null); setOffset(0); }}>Сбросить</button>
                </span>
              </div>
            ) : (
              <PartPicker label="Запчасть" onPick={(p) => { setPart({ id: p.id, name: p.name }); setOffset(0); }} />
            )}
          </div>
        )}
      </div>
      {err && err.code !== "validation_error" && (
        <div className="flex items-center gap-2">
          <div className="flex-1"><Alert>{err.message}</Alert></div>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      )}
      {q.isLoading && <Loading />}
      {q.data && items.length === 0 && <p className="py-8 text-center text-sm text-muted">{emptyText}</p>}
      {items.length > 0 && (
        <>
          <ResponsiveList
            items={items}
            id={(m) => m.id}
            head={["Дата", "Тип", "Позиция", "Количество", "Остаток после", "Сумма", "Основание", "Кто", ""]}
            row={(m) => [
              <span key="d" className="whitespace-nowrap">{fmtDateTime(m.created_at)}</span>,
              <span key="t">{MOVEMENT_LABELS[m.movement_type]}{m.reversed && <> <Badge tone="warning">сторнировано</Badge></>}</span>,
              <span key="p"><span className="font-medium">{m.part.name}</span> <span className="text-muted">{m.part.sku}</span></span>,
              <span key="q" className="whitespace-nowrap">{fmtSignedQty(m.quantity)} {unitLabel(m.part.unit)}</span>,
              <span key="b" className="whitespace-nowrap">{fmtQty(m.balance_after)}</span>,
              <span key="s" className="whitespace-nowrap">{formatMoney(m.total.replace(/^-/, ""))}</span>,
              <span key="r">{orderLink(m) ?? m.reason ?? m.supplier ?? "—"}</span>,
              m.created_by.full_name,
              canReverse(m) ? <Button key="x" variant="ghost" aria-label={`Сторно: ${m.part.name}`} onClick={() => setReverse(m)}>Сторно</Button> : "",
            ]}
            card={(m) => (
              <>
                <div className="flex items-start justify-between gap-2">
                  <div className="font-medium">{m.part.name}</div>
                  <div className="whitespace-nowrap font-medium">{fmtSignedQty(m.quantity)} {unitLabel(m.part.unit)}</div>
                </div>
                <div className="mt-1 text-sm text-muted">
                  {MOVEMENT_LABELS[m.movement_type]} · {fmtDateTime(m.created_at)} · остаток {fmtQty(m.balance_after)}
                </div>
                <div className="mt-1 text-sm">{orderLink(m) ?? m.reason ?? m.supplier ?? ""} <span className="text-muted">{m.created_by.full_name}</span></div>
                <div className="mt-2 flex items-center justify-between">
                  {m.reversed ? <Badge tone="warning">сторнировано</Badge> : <span />}
                  {canReverse(m) && <Button variant="secondary" aria-label={`Сторно: ${m.part.name}`} onClick={() => setReverse(m)}>Сторно</Button>}
                </div>
              </>
            )}
          />
          <Pager offset={offset} size={STOCK_PAGE_SIZE} total={q.data?.total ?? 0} onChange={setOffset} />
        </>
      )}
      {reverse && <ReverseModal movement={reverse} onClose={() => setReverse(null)} />}
    </div>
  );
}
