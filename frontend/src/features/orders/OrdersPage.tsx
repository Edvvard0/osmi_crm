import clsx from "clsx";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useActiveLocation } from "@/features/locations/api";
import { useDebounced, Pager } from "@/pages/catalog/common";
import { formatMoney } from "@/shared/lib/money";
import { readPref, writePref } from "@/shared/lib/storage";
import { useMediaQuery } from "@/shared/lib/useMediaQuery";
import { useToast } from "@/shared/ui/toast";
import { Badge, Button, Checkbox, Input, LinkButton, Select, Table, Td, Th } from "@/shared/ui/ui";

import {
  EMPTY_FILTERS,
  ORDERS_PAGE_SIZE,
  type OrderFilters,
  orderErrorText,
  useChangeOrderStatus,
  useMechanics,
  useOrderBoard,
  useOrders,
} from "./api";
import {
  ORDER_DEPARTMENT_LABELS,
  STATUS_LABELS,
  STATUS_ORDER,
  TRANSITIONS,
  type WorkOrderDepartment,
  type WorkOrderListItem,
  type WorkOrderStatus,
} from "./types";
import { LoadError, PaymentBadge, Skeleton, StatusBadge, fmtDateTime, useTzOf, vehicleName } from "./ui";
import { maskPhone } from "@/shared/lib/masks";

type View = "table" | "kanban";
const VIEW_KEY = "orders.view";
const SAVED_KEY = "orders.savedFilters";

type SavedFilters = Record<string, Omit<OrderFilters, "offset" | "locationId">>;
function readSaved(): SavedFilters {
  try {
    const v = JSON.parse(readPref(SAVED_KEY) ?? "{}") as unknown;
    return v && typeof v === "object" ? (v as SavedFilters) : {};
  } catch {
    return {};
  }
}

function initialFilters(sp: URLSearchParams): OrderFilters {
  const status = (sp.get("status") ?? "").split(",").filter((s): s is WorkOrderStatus => s in STATUS_LABELS);
  return { ...EMPTY_FILTERS, status, overdue: sp.get("overdue") === "true" };
}

export function OrdersPage() {
  const [sp] = useSearchParams();
  const loc = useActiveLocation();
  const toast = useToast();
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [view, setView] = useState<View>(() => (readPref(VIEW_KEY) === "kanban" ? "kanban" : "table"));
  const [f, setF] = useState<OrderFilters>(() => initialFilters(sp));
  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput.trim(), 300);
  const [saved, setSaved] = useState<SavedFilters>(readSaved);
  const [saveName, setSaveName] = useState("");

  const locationId = loc.value === "all" ? "" : loc.value;
  const filters = useMemo<OrderFilters>(() => ({ ...f, search, locationId }), [f, search, locationId]);
  const kanban = view === "kanban" && !isMobile;

  const list = useOrders(filters);
  const board = useOrderBoard(filters, kanban);
  const mech = useMechanics(locationId);
  const tzOf = useTzOf();

  useEffect(() => {
    setF((x) => (x.offset === 0 ? x : { ...x, offset: 0 }));
  }, [search, locationId]);

  function patch(p: Partial<OrderFilters>) {
    setF((x) => ({ ...x, offset: 0, ...p }));
  }
  function setViewPersist(v: View) {
    setView(v);
    writePref(VIEW_KEY, v);
  }
  function saveCurrent() {
    const name = saveName.trim();
    if (!name) return;
    const { offset: _o, locationId: _l, ...rest } = { ...f, search: searchInput };
    const next = { ...saved, [name]: rest };
    setSaved(next);
    writePref(SAVED_KEY, JSON.stringify(next));
    setSaveName("");
  }
  function applySaved(name: string) {
    const s = saved[name];
    if (!s) return;
    setSearchInput(s.search);
    patch({ ...s });
  }
  function dropSaved(name: string) {
    const { [name]: _x, ...rest } = saved;
    setSaved(rest);
    writePref(SAVED_KEY, JSON.stringify(rest));
  }

  const filtersActive = f.status.length > 0 || !!f.department || !!f.mechanicId || !!f.dateFrom || !!f.dateTo || f.overdue || !!search;
  const items = list.data?.items ?? [];
  const mechanics = mech.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Заказ-наряды</h1>
        <div className="flex items-center gap-2">
          {!isMobile && (
            <div role="group" aria-label="Вид" className="inline-flex overflow-hidden rounded border border-border">
              {(["table", "kanban"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={view === v}
                  onClick={() => setViewPersist(v)}
                  className={clsx("min-h-10 px-3 text-sm", view === v ? "bg-accent text-accent-fg" : "bg-surface text-fg hover:bg-bg")}
                >
                  {v === "table" ? "Таблица" : "Канбан"}
                </button>
              ))}
            </div>
          )}
          <LinkButton to="/orders/new">Новый заказ</LinkButton>
        </div>
      </div>

      <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => e.preventDefault()} aria-label="Фильтры">
        <Input label="Поиск" type="search" placeholder="Номер, госномер, VIN, клиент, телефон" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        {!kanban && (
          <Select label="Статус" value={f.status[0] ?? ""} onChange={(e) => patch({ status: e.target.value ? [e.target.value as WorkOrderStatus] : [] })}>
            <option value="">Все статусы</option>
            {[...STATUS_ORDER, "cancelled" as const].map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </Select>
        )}
        <Select label="Отдел" value={f.department} onChange={(e) => patch({ department: e.target.value as "" | WorkOrderDepartment })}>
          <option value="">Все отделы</option>
          {(Object.keys(ORDER_DEPARTMENT_LABELS) as WorkOrderDepartment[]).map((d) => (
            <option key={d} value={d}>{ORDER_DEPARTMENT_LABELS[d]}</option>
          ))}
        </Select>
        {mechanics.length > 0 && (
          <Select label="Механик" value={f.mechanicId} onChange={(e) => patch({ mechanicId: e.target.value })}>
            <option value="">Все механики</option>
            {mechanics.map((m) => (
              <option key={m.id} value={m.id}>{m.full_name}</option>
            ))}
          </Select>
        )}
        {!kanban && (
          <>
            <Input label="Создан с" type="date" value={f.dateFrom} onChange={(e) => patch({ dateFrom: e.target.value })} />
            <Input label="Создан по" type="date" value={f.dateTo} onChange={(e) => patch({ dateTo: e.target.value })} />
          </>
        )}
        <Checkbox label="Только просроченные" checked={f.overdue} onChange={(e) => patch({ overdue: e.target.checked })} />
        <div className="flex flex-wrap items-end gap-2 sm:col-span-2">
          {Object.keys(saved).length > 0 && (
            <Select label="Сохранённые фильтры" value="" onChange={(e) => applySaved(e.target.value)}>
              <option value="">Выбрать…</option>
              {Object.keys(saved).map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          )}
          <Input label="Имя фильтра" value={saveName} onChange={(e) => setSaveName(e.target.value)} className="w-40" />
          <Button type="button" variant="secondary" disabled={!saveName.trim()} onClick={saveCurrent}>Сохранить фильтр</Button>
          {Object.keys(saved).length > 0 && (
            <Button type="button" variant="ghost" onClick={() => dropSaved(Object.keys(saved)[Object.keys(saved).length - 1])}>Удалить последний</Button>
          )}
        </div>
      </form>

      {kanban ? (
        <Kanban
          q={board}
          tzOf={tzOf}
          onError={(e) => toast.push("error", orderErrorText(e))}
        />
      ) : list.isLoading ? (
        <Skeleton lines={5} />
      ) : list.error ? (
        <LoadError error={list.error} onRetry={() => void list.refetch()} />
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center">
          <p className="text-sm text-muted">{filtersActive ? "Ничего не найдено" : "Заказов пока нет"}</p>
          {!filtersActive && <LinkButton to="/orders/new" className="mt-3">Новый заказ</LinkButton>}
        </div>
      ) : (
        <div className="space-y-3">
          {isMobile ? (
            <ul className="space-y-2">
              {items.map((o) => (
                <li key={o.id}>
                  <OrderCard o={o} tz={tzOf(o.location_id)} />
                </li>
              ))}
            </ul>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Номер</Th>
                  <Th>Дата</Th>
                  <Th>Авто</Th>
                  <Th>Клиент</Th>
                  <Th>Отдел</Th>
                  <Th>Статус</Th>
                  <Th>Механики</Th>
                  <Th>Сумма</Th>
                  <Th>Оплата</Th>
                  <Th>Срок</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((o) => {
                  const tz = tzOf(o.location_id);
                  return (
                    <tr key={o.id}>
                      <Td><Link className="font-medium underline" to={`/orders/${encodeURIComponent(o.id)}`}>{o.number}</Link></Td>
                      <Td>{fmtDateTime(o.created_at, tz)}</Td>
                      <Td>{vehicleName(o.vehicle)}</Td>
                      <Td>{o.client.full_name}</Td>
                      <Td>{ORDER_DEPARTMENT_LABELS[o.department]}</Td>
                      <Td><StatusBadge status={o.status} /></Td>
                      <Td>{o.mechanics.map((m) => m.full_name).join(", ") || "—"}</Td>
                      <Td>{formatMoney(o.total)}</Td>
                      <Td><PaymentBadge status={o.payment_status} /></Td>
                      <Td><Deadline o={o} tz={tz} /></Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
          <Pager offset={f.offset} size={ORDERS_PAGE_SIZE} total={list.data?.total ?? 0} onChange={(offset) => setF((x) => ({ ...x, offset }))} />
        </div>
      )}
    </div>
  );
}

function Deadline({ o, tz }: { o: WorkOrderListItem; tz: string }) {
  if (!o.planned_ready_at) return <span className="text-muted">—</span>;
  return (
    <span className={clsx(o.is_overdue && "font-medium text-danger")}>
      {fmtDateTime(o.planned_ready_at, tz)}
      {o.is_overdue && <span> · просрочен</span>}
    </span>
  );
}

function OrderCard({ o, tz, draggable, onDragStart }: { o: WorkOrderListItem; tz: string; draggable?: boolean; onDragStart?: (e: React.DragEvent) => void }) {
  return (
    <div
      draggable={draggable}
      onDragStart={onDragStart}
      className={clsx("space-y-1 rounded-lg border bg-surface p-3 text-sm", o.is_overdue ? "border-danger/60" : "border-border", draggable && "cursor-grab")}
    >
      <div className="flex items-center justify-between gap-2">
        <Link className="font-medium underline" to={`/orders/${encodeURIComponent(o.id)}`}>{o.number}</Link>
        <StatusBadge status={o.status} />
      </div>
      <p className="break-words">{vehicleName(o.vehicle)} · {o.client.full_name}</p>
      <p className="text-xs text-muted">{maskPhone(o.client.phone)}</p>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{formatMoney(o.total)}</span>
        <Deadline o={o} tz={tz} />
      </div>
      {o.mechanics.length > 0 && <p className="text-xs text-muted">{o.mechanics.map((m) => m.full_name).join(", ")}</p>}
      {o.items_count > 0 && <p className="text-xs text-muted">Работ: {o.items_done_count}/{o.items_count}</p>}
    </div>
  );
}

function Kanban({
  q,
  tzOf,
  onError,
}: {
  q: ReturnType<typeof useOrderBoard>;
  tzOf: (id: string | undefined) => string;
  onError: (e: unknown) => void;
}) {
  const change = useChangeOrderStatus();
  const [drag, setDrag] = useState<WorkOrderListItem | null>(null);
  const [over, setOver] = useState<WorkOrderStatus | null>(null);

  if (q.isLoading) return <Skeleton lines={5} />;
  if (q.error) return <LoadError error={q.error} onRetry={() => void q.refetch()} />;
  const columns = q.data?.columns ?? [];

  const canDrop = (to: WorkOrderStatus) => !!drag && TRANSITIONS[drag.status].includes(to);

  function drop(to: WorkOrderStatus) {
    const d = drag;
    setDrag(null);
    setOver(null);
    if (!d || !TRANSITIONS[d.status].includes(to)) return;
    // Карточка остаётся на месте, пока сервер не подтвердит; при ошибке — сообщение и повторный запрос доски.
    change.mutate({ id: d.id, version: d.version, status: to }, { onError });
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-2" aria-label="Канбан-доска">
      {columns.map((c) => {
        const accept = canDrop(c.status);
        return (
          <section
            key={c.status}
            aria-label={STATUS_LABELS[c.status]}
            onDragOver={(e) => {
              if (accept) {
                e.preventDefault();
                setOver(c.status);
              }
            }}
            onDragLeave={() => setOver((s) => (s === c.status ? null : s))}
            onDrop={(e) => {
              e.preventDefault();
              drop(c.status);
            }}
            className={clsx(
              "w-64 shrink-0 rounded-lg border bg-bg p-2",
              over === c.status ? "border-accent" : "border-border",
              drag && !accept && drag.status !== c.status && "opacity-50",
            )}
          >
            <h2 className="mb-2 flex items-center justify-between px-1 text-sm font-semibold">
              <span>{STATUS_LABELS[c.status]}</span>
              <Badge>{c.total}</Badge>
            </h2>
            <ul className="space-y-2">
              {c.items.map((o) => (
                <li key={o.id}>
                  <OrderCard
                    o={o}
                    tz={tzOf(o.location_id)}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", o.id);
                      e.dataTransfer.effectAllowed = "move";
                      setDrag(o);
                    }}
                  />
                </li>
              ))}
              {c.items.length === 0 && <li className="px-1 py-3 text-xs text-muted">Пусто</li>}
            </ul>
            {c.total > c.items.length && <p className="mt-2 px-1 text-xs text-muted">Показано {c.items.length} из {c.total}</p>}
          </section>
        );
      })}
    </div>
  );
}
