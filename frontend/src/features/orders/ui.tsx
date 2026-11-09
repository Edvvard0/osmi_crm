import clsx from "clsx";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useEntityOrders } from "./api";
import { useLocations } from "@/features/locations/api";
import { toAppError } from "@/shared/api/errors";
import { formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Badge, Button, Table, Td, Th } from "@/shared/ui/ui";
import { Pager } from "@/pages/catalog/common";

import { safeZone, toZonedIso, zonedTimeToMs } from "../appointments/time";
import {
  PAYMENT_LABELS,
  STATUS_LABELS,
  type PaymentStatus,
  type VehicleRef,
  type WorkOrderListItem,
  type WorkOrderStatus,
} from "./types";

type Tone = "neutral" | "success" | "warning" | "danger";

const STATUS_TONE: Record<WorkOrderStatus, Tone> = {
  new: "neutral",
  diagnostics: "neutral",
  awaiting_approval: "warning",
  in_progress: "neutral",
  awaiting_parts: "warning",
  quality_check: "neutral",
  ready: "success",
  closed: "neutral",
  cancelled: "danger",
};
const STATUS_GLYPH: Record<WorkOrderStatus, string> = {
  new: "○",
  diagnostics: "◔",
  awaiting_approval: "◑",
  in_progress: "●",
  awaiting_parts: "❚❚",
  quality_check: "◕",
  ready: "✓",
  closed: "✓✓",
  cancelled: "✕",
};

export function StatusBadge({ status }: { status: WorkOrderStatus }) {
  return (
    <Badge tone={STATUS_TONE[status]}>
      <span aria-hidden="true" className="mr-1">{STATUS_GLYPH[status]}</span>
      {STATUS_LABELS[status]}
    </Badge>
  );
}

export function PaymentBadge({ status }: { status: PaymentStatus }) {
  return <Badge tone={status === "paid" ? "success" : status === "partial" ? "warning" : "neutral"}>{PAYMENT_LABELS[status]}</Badge>;
}

/** Дата и время в поясе точки: «09.11 14:30». */
export function fmtDateTime(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  return new Intl.DateTimeFormat("ru-RU", { timeZone: safeZone(tz), day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }).format(ms);
}
export function fmtDate(iso: string | null | undefined, tz: string): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  return new Intl.DateTimeFormat("ru-RU", { timeZone: safeZone(tz), day: "2-digit", month: "2-digit", year: "numeric" }).format(ms);
}

/** Функция «id точки → часовой пояс» для списков, где заказы разных точек. */
export function useTzOf(): (locationId: string | undefined) => string {
  const q = useLocations();
  return (id) => q.data?.find((l) => l.id === id)?.timezone ?? "Europe/Moscow";
}

export function vehicleName(v: VehicleRef): string {
  return v.plate_number || `${v.make} ${v.model}`.trim();
}

/** Значение для <input type="datetime-local"> из ISO в поясе точки. */
export function isoToLocalInput(iso: string | null | undefined, tz: string): string {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: safeZone(tz),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(ms);
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${g("year")}-${g("month")}-${g("day")}T${g("hour")}:${g("minute")}`;
}

/** Значение datetime-local (время точки) → ISO со смещением пояса точки; пусто → null. */
export function localInputToIso(v: string, tz: string): string | null {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/.exec(v);
  if (!m) return null;
  return toZonedIso(zonedTimeToMs(m[1], Number(m[2]) * 60 + Number(m[3]), tz), tz);
}

export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div role="status" aria-label="Загрузка" className="animate-pulse space-y-3">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={clsx("h-5 rounded bg-border/60", i === 0 ? "w-1/3" : "w-full")} />
      ))}
    </div>
  );
}

/** «Не удалось загрузить» + «Повторить» + код обращения. */
export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const e = toAppError(error);
  return (
    <div role="alert" className="rounded-lg border border-border bg-surface p-4 text-sm">
      <p className="font-medium">Не удалось загрузить</p>
      <p className="mt-1 text-muted">
        {e.message}
        {e.requestId ? ` · Код обращения: ${e.requestId}` : ""}
      </p>
      <Button className="mt-3" variant="secondary" onClick={onRetry}>Повторить</Button>
    </div>
  );
}

/** 409 version_conflict: заказ изменил другой сотрудник. */
export function ConflictDialog({ onRefresh }: { onRefresh: () => void }) {
  return (
    <Modal title="Данные изменил другой сотрудник" onClose={onRefresh}>
      <p className="text-sm text-muted">Заказ был изменён. Обновите страницу, чтобы увидеть актуальные данные, и повторите действие.</p>
      <div className="mt-4 flex justify-end">
        <Button onClick={onRefresh}>Обновить</Button>
      </div>
    </Modal>
  );
}

/** Поле десятичного числа: правка по blur/Enter; неверный ввод откатывается. `onCommit` получает нормализованную строку. */
export function DecimalField({
  label,
  value,
  scale = 2,
  max,
  disabled,
  title,
  onCommit,
  className,
}: {
  label: string;
  value: string;
  scale?: number;
  max?: number;
  disabled?: boolean;
  title?: string;
  onCommit: (v: string) => void;
  className?: string;
}) {
  const [text, setText] = useState(toInput(value));
  const [bad, setBad] = useState(false);
  useEffect(() => {
    setText(toInput(value));
    setBad(false);
  }, [value]);

  function commit() {
    const parsed = parseDecimal(text, scale);
    if (parsed === null || (max !== undefined && Number(parsed) > max)) {
      setBad(true);
      return;
    }
    setBad(false);
    if (parsed !== value) onCommit(parsed);
    else setText(toInput(value));
  }

  return (
    <input
      aria-label={label}
      aria-invalid={bad}
      title={bad ? "Неверное значение" : title}
      inputMode="decimal"
      disabled={disabled}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      className={clsx(
        "min-h-9 w-24 rounded border bg-surface px-2 text-right text-sm text-fg disabled:cursor-not-allowed disabled:bg-bg disabled:text-muted",
        bad ? "border-danger" : "border-border",
        className,
      )}
    />
  );
}

/** Блок «История заказов» клиента/авто (MG-09, MG-10). */
export function EntityOrders({ kind, id }: { kind: "clients" | "vehicles"; id: string }) {
  const [offset, setOffset] = useState(0);
  const q = useEntityOrders(kind, id, offset, 10);
  const tzOf = useTzOf();
  const items: WorkOrderListItem[] = q.data?.items ?? [];

  if (q.isLoading) return <Skeleton lines={2} />;
  if (q.error) return <LoadError error={q.error} onRetry={() => void q.refetch()} />;
  if (items.length === 0) return <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Заказов пока нет</p>;
  return (
    <div className="space-y-2">
      <Table>
        <thead>
          <tr>
            <Th>Номер</Th>
            <Th>Дата</Th>
            {kind === "clients" && <Th>Авто</Th>}
            <Th>Статус</Th>
            <Th>Сумма</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((o) => (
            <tr key={o.id}>
              <Td><Link className="font-medium underline" to={`/orders/${encodeURIComponent(o.id)}`}>{o.number}</Link></Td>
              <Td>{fmtDate(o.created_at, tzOf(o.location_id))}</Td>
              {kind === "clients" && <Td>{vehicleName(o.vehicle)}</Td>}
              <Td><StatusBadge status={o.status} /></Td>
              <Td>{formatMoney(o.total)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Pager offset={offset} size={10} total={q.data?.total ?? 0} onChange={setOffset} />
    </div>
  );
}
