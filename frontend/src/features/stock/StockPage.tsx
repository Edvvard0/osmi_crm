import clsx from "clsx";
import { type ComponentType, type FormEvent, lazy, Suspense, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Pager, ResponsiveList, useDebounced } from "@/pages/catalog/common";
import { api } from "@/shared/api/client";
import { fieldMessage, toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Checkbox, Input, LinkButton, Loading, Select, Textarea } from "@/shared/ui/ui";

import {
  STOCK_PAGE_SIZE,
  useStock,
  useStockLocation,
  useTransfer,
  useWriteOff,
} from "./api";
import { InventoryTab } from "./InventoryTab";
import { MovementsView } from "./MovementsView";
import { type Line, LinesEditor, OpError, PartPicker, Stat, addLine } from "./components";
import { fmtQty, parseQty, unitLabel } from "./format";
import type { StockBalance, StockScope, StockSort } from "./types";

export type StockTab = "balances" | "movements" | "requests" | "inventory";

const TABS: { id: StockTab; label: string; to: string }[] = [
  { id: "balances", label: "Остатки", to: "/stock" },
  { id: "movements", label: "Движения", to: "/stock/movements" },
  { id: "requests", label: "Заявки механиков", to: "/stock/requests" },
  { id: "inventory", label: "Инвентаризация", to: "/stock/inventory" },
];

/** Селектор точки + заголовок: общий для страниц склада. */
export function LocationSelect({ id = "stock-loc" }: { id?: string }) {
  const { locationId, setLocationId, items } = useStockLocation();
  if (items.length <= 1) return <span className="text-sm text-muted">{items[0]?.name ?? ""}</span>;
  return (
    <div className="w-full sm:w-64">
      <Select id={id} label="Точка" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
        {items.map((l) => (
          <option key={l.id} value={l.id}>{l.name}</option>
        ))}
      </Select>
    </div>
  );
}

// Панель заявок механиков — компонент модуля 6; если его ещё нет в сборке, показываем ссылку на /part-requests.
const panelModules = import.meta.glob<{ PartRequestsPanel: ComponentType<{ locationId?: string }> }>("../mechanic/PartRequestsPanel.tsx");
const PanelLoader = Object.values(panelModules)[0];
const PartRequestsPanel = PanelLoader ? lazy(() => PanelLoader().then((m) => ({ default: m.PartRequestsPanel }))) : null;

function RequestsTab({ locationId }: { locationId: string }) {
  if (!PartRequestsPanel) {
    return (
      <p className="py-8 text-center text-sm text-muted">
        Заявки механиков: <Link className="underline" to="/part-requests">перейти к списку</Link>
      </p>
    );
  }
  return (
    <Suspense fallback={<Loading />}>
      <PartRequestsPanel locationId={locationId} />
    </Suspense>
  );
}

function useNewRequests(locationId: string) {
  return useQuery({
    queryKey: ["stock", "requests-summary", locationId],
    queryFn: () => api<{ new: number; approved: number }>(`/part-requests/summary?location_id=${encodeURIComponent(locationId)}`),
    enabled: !!locationId && !!PartRequestsPanel,
    retry: false,
    meta: { silent: true },
  });
}

export function StockPage({ tab }: { tab: StockTab }) {
  const { locationId, items, loading, isDirector } = useStockLocation();
  const [sp] = useSearchParams();
  const [writeOff, setWriteOff] = useState(false);
  const [transfer, setTransfer] = useState(false);
  const summary = useNewRequests(locationId);
  const newCount = summary.data?.new ?? 0;
  const suffix = locationId ? `?location_id=${encodeURIComponent(locationId)}` : sp.toString() ? `?${sp.toString()}` : "";

  if (loading) return <Loading />;
  if (!locationId) return <p className="py-8 text-center text-sm text-muted">Нет доступных точек</p>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-xl font-semibold">Склад</h1>
        <LocationSelect />
      </div>
      <div role="tablist" aria-label="Разделы склада" className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((t) => (
          <Link
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            to={`${t.to}${suffix}`}
            className={clsx(
              "flex min-h-10 shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 text-sm font-medium",
              tab === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            {t.label}
            {t.id === "requests" && newCount > 0 && <Badge tone="warning">{newCount}</Badge>}
          </Link>
        ))}
      </div>
      {tab === "balances" && (
        <>
          <div className="flex flex-wrap gap-2">
            <LinkButton to={`/stock/receipt${suffix}`}>Приход</LinkButton>
            <Button variant="secondary" onClick={() => setWriteOff(true)}>Списание</Button>
            {isDirector && items.length > 1 && <Button variant="secondary" onClick={() => setTransfer(true)}>Переместить</Button>}
          </div>
          <BalancesTab locationId={locationId} suffix={suffix} />
        </>
      )}
      {tab === "movements" && <MovementsView locationId={locationId} />}
      {tab === "requests" && <RequestsTab locationId={locationId} />}
      {tab === "inventory" && <InventoryTab locationId={locationId} />}
      {writeOff && <WriteOffModal locationId={locationId} onClose={() => setWriteOff(false)} />}
      {transfer && <TransferModal fromId={locationId} onClose={() => setTransfer(false)} />}
    </div>
  );
}

function BalancesTab({ locationId, suffix }: { locationId: string; suffix: string }) {
  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput.trim());
  const [lowOnly, setLowOnly] = useState(false);
  const [sortKey, setSortKey] = useState("name:asc");
  const [offset, setOffset] = useState(0);
  const [sort, order] = sortKey.split(":") as [StockSort, "asc" | "desc"];
  const scope: StockScope = lowOnly ? "low" : "stocked";
  const q = useStock({ location_id: locationId, search, scope, sort, order }, offset);
  const items = q.data?.items ?? [];
  const totals = q.data?.totals;
  const err = q.error ? toAppError(q.error) : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <Input
            id="stock-search"
            label="Поиск"
            type="search"
            placeholder="Артикул, название, бренд или штрихкод"
            value={searchInput}
            onChange={(e) => { setSearchInput(e.target.value); setOffset(0); }}
          />
        </div>
        <div className="w-full sm:w-56">
          <Select id="stock-sort" label="Сортировка" value={sortKey} onChange={(e) => { setSortKey(e.target.value); setOffset(0); }}>
            <option value="name:asc">По названию</option>
            <option value="sku:asc">По артикулу</option>
            <option value="quantity:asc">Остаток: меньше</option>
            <option value="quantity:desc">Остаток: больше</option>
            <option value="stock_value:desc">Стоимость: больше</option>
            <option value="stock_value:asc">Стоимость: меньше</option>
          </Select>
        </div>
        <Checkbox label="Только дефицит" checked={lowOnly} onChange={(e) => { setLowOnly(e.target.checked); setOffset(0); }} />
      </div>
      {totals && (
        <div className="grid grid-cols-3 gap-2" aria-label="Итоги">
          <Stat label="Позиций" value={totals.positions} />
          <Stat label="Дефицит" value={totals.low_count} tone={totals.low_count > 0 ? "danger" : undefined} />
          <Stat label="Стоимость склада" value={formatMoney(totals.stock_value)} />
        </div>
      )}
      {err && (
        <div className="flex items-center gap-2">
          <div className="flex-1"><Alert>{err.message}</Alert></div>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      )}
      {q.isLoading && <TableSkeleton />}
      {q.data && items.length === 0 && (
        <p className="py-8 text-center text-sm text-muted">{search || lowOnly ? "Ничего не найдено" : "На складе пока ничего нет"}</p>
      )}
      {items.length > 0 && (
        <>
          <ResponsiveList
            items={items}
            id={(b) => b.part.id}
            head={["Артикул", "Название", "Ед.", "Остаток", "Минимум", "Ср. себестоимость", "Стоимость"]}
            row={(b) => {
              const low = b.is_low ? "font-medium text-danger" : "";
              return [
                b.part.sku,
                <Link key="n" className="font-medium underline-offset-2 hover:underline" to={`/stock/${b.part.id}${suffix}`}>{b.part.name}</Link>,
                unitLabel(b.part.unit),
                <span key="q" className={clsx("whitespace-nowrap", low)}>{fmtQty(b.quantity)}</span>,
                <span key="m" className="whitespace-nowrap">{fmtQty(b.min_quantity)}</span>,
                <span key="c" className="whitespace-nowrap">{formatMoney(b.avg_cost)}</span>,
                <span key="v" className="whitespace-nowrap">{formatMoney(b.stock_value)}</span>,
              ];
            }}
            card={(b) => <BalanceCard b={b} suffix={suffix} />}
          />
          <Pager offset={offset} size={STOCK_PAGE_SIZE} total={q.data?.total ?? 0} onChange={setOffset} />
        </>
      )}
    </div>
  );
}

function BalanceCard({ b, suffix }: { b: StockBalance; suffix: string }) {
  return (
    <>
      <Link to={`/stock/${b.part.id}${suffix}`} className="font-medium underline-offset-2 hover:underline">{b.part.name}</Link>
      <div className="mt-1 text-sm text-muted">{b.part.sku}</div>
      <div className="mt-1 flex items-center justify-between text-sm">
        <span className={clsx("font-medium", b.is_low && "text-danger")}>
          {fmtQty(b.quantity)} {unitLabel(b.part.unit)}{b.is_low && " · дефицит"}
        </span>
        <span>{formatMoney(b.stock_value)}</span>
      </div>
      <div className="mt-1 text-xs text-muted">Минимум {fmtQty(b.min_quantity)} · себестоимость {formatMoney(b.avg_cost)}</div>
    </>
  );
}

export function TableSkeleton() {
  return (
    <div role="status" aria-label="Загрузка" className="space-y-2">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-border/50" />
      ))}
    </div>
  );
}

/* ---------- Списание ---------- */

function WriteOffModal({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const m = useWriteOff();
  const toast = useToast();
  const [lines, setLines] = useState<Line[]>([]);
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const err = m.error ? toAppError(m.error) : null;
  const r = reason.trim();
  const reasonBad = r.length < 3 || r.length > 500;

  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    const items = lines.map((l) => ({ part_id: l.part.id, quantity: parseQty(l.qty) }));
    if (lines.length === 0 || reasonBad || items.some((i) => i.quantity === null)) return;
    m.mutate(
      { location_id: locationId, reason: r, items: items as { part_id: string; quantity: string }[] },
      { onSuccess: () => { toast.push("success", "Списание проведено"); onClose(); } },
    );
  }

  return (
    <Modal title="Списание" onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <PartPicker onPick={(p) => setLines((ls) => addLine(ls, p))} />
        <LinesEditor lines={lines} setLines={setLines} error={err} invalid={tried} />
        {err?.fields.items !== undefined && <p role="alert" className="text-xs text-danger">{fieldMessage(err, "items")}</p>}
        <Textarea id="writeoff-reason" label="Причина" value={reason} onChange={(e) => setReason(e.target.value)} error={tried && reasonBad ? "Причина: от 3 до 500 символов" : fieldMessage(err, "reason")} />
        <OpError err={m.error} lines={lines} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={m.isPending} disabled={lines.length === 0}>Списать</Button>
        </div>
      </form>
    </Modal>
  );
}

/* ---------- Перемещение (директор) ---------- */

function TransferModal({ fromId, onClose }: { fromId: string; onClose: () => void }) {
  const { items: locs } = useStockLocation();
  const m = useTransfer();
  const toast = useToast();
  const others = locs.filter((l) => l.id !== fromId && l.is_active);
  const [toId, setToId] = useState(others[0]?.id ?? "");
  const [lines, setLines] = useState<Line[]>([]);
  const [comment, setComment] = useState("");
  const [tried, setTried] = useState(false);
  const err = m.error ? toAppError(m.error) : null;
  const from = locs.find((l) => l.id === fromId);

  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    const items = lines.map((l) => ({ part_id: l.part.id, quantity: parseQty(l.qty) }));
    if (lines.length === 0 || !toId || items.some((i) => i.quantity === null)) return;
    m.mutate(
      {
        from_location_id: fromId,
        to_location_id: toId,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
        items: items as { part_id: string; quantity: string }[],
      },
      { onSuccess: () => { toast.push("success", "Перемещение проведено"); onClose(); } },
    );
  }

  return (
    <Modal title="Перемещение между точками" onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="text-sm">
            <span className="mb-1 block text-muted">Откуда</span>
            <span className="flex min-h-10 items-center font-medium">{from?.name ?? "—"}</span>
          </div>
          <Select id="transfer-to" label="Куда" value={toId} onChange={(e) => setToId(e.target.value)} error={fieldMessage(err, "to_location_id")}>
            {others.map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </Select>
        </div>
        <PartPicker onPick={(p) => setLines((ls) => addLine(ls, p))} />
        <LinesEditor lines={lines} setLines={setLines} error={err} invalid={tried} />
        {err?.fields.items !== undefined && <p role="alert" className="text-xs text-danger">{fieldMessage(err, "items")}</p>}
        <Textarea id="transfer-comment" label="Комментарий" value={comment} onChange={(e) => setComment(e.target.value)} error={fieldMessage(err, "comment")} />
        <OpError err={m.error} lines={lines} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={m.isPending} disabled={lines.length === 0 || !toId}>Переместить</Button>
        </div>
      </form>
    </Modal>
  );
}
