import clsx from "clsx";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { ForceCloseDialog } from "@/features/cash/ForceCloseDialog";
import { OrderPayments } from "@/features/cash/OrderPayments";
import { cashErrorText } from "@/features/cash/lib";
import { OrderPartRequests } from "@/features/mechanic/PartRequestsPanel";
import { ReopenItemButton } from "@/features/mechanic/ReopenItemButton";
import { fmtQty, stockErrorText } from "@/features/stock/format";
import { NotFoundPage } from "@/pages/ErrorPage";
import { useDebounced } from "@/pages/catalog/common";
import { toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS, type Department } from "@/shared/api/types";
import { maskPhone, normalizePhone } from "@/shared/lib/masks";
import { formatHours, formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Alert, Badge, Button, Input, LinkButton, Select, Table, Td, Textarea, Th } from "@/shared/ui/ui";

import {
  type OrderCall,
  orderErrorText,
  useAddComment,
  useCatalogParts,
  useCatalogServices,
  useDuplicateOrder,
  useLocationTz,
  type MechanicRef,
  useMechanics,
  useOrder,
  useOrderCall,
  useOrderComments,
  useOrderHistory,
} from "./api";
import {
  ITEM_STATUS_GLYPH,
  ITEM_STATUS_LABELS,
  NEXT_STATUS,
  ORDER_DEPARTMENT_LABELS,
  STATUS_LABELS,
  STATUS_ORDER,
  isClosedOrder,
  type WorkOrder,
  type WorkOrderItem,
  type WorkOrderPart,
  type WorkOrderStatus,
} from "./types";
import { ConflictDialog, DecimalField, LoadError, PaymentBadge, Skeleton, StatusBadge, fmtDateTime, isoToLocalInput, localInputToIso } from "./ui";

type Run = (c: OrderCall, done?: () => void) => void;
type Tab = "works" | "parts" | "comments" | "history";
const TAB_LABELS: Record<Tab, string> = { works: "Работы", parts: "Запчасти", comments: "Комментарии", history: "История" };

export function OrderPage() {
  const { id = "" } = useParams();
  const q = useOrder(id);
  if (q.isLoading) return <Skeleton lines={8} />;
  if (q.error) {
    if (toAppError(q.error).status === 404) return <NotFoundPage />;
    return <LoadError error={q.error} onRetry={() => void q.refetch()} />;
  }
  if (!q.data) return null;
  return <OrderView key={q.data.id} order={q.data} refresh={() => void q.refetch()} />;
}

function OrderView({ order, refresh }: { order: WorkOrder; refresh: () => void }) {
  const me = useMe();
  const isDirector = me.role === "director";
  const navigate = useNavigate();
  const tz = useLocationTz(order.location_id);
  const call = useOrderCall(order.id);
  const dup = useDuplicateOrder(order.id);
  const mech = useMechanics(order.location_id);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [tab, setTab] = useState<Tab>("works");
  const [menu, setMenu] = useState(false);
  const [dialog, setDialog] = useState<null | "cancel" | "edit" | "force_close">(null);
  const readOnly = isClosedOrder(order.status);
  const busy = call.isPending || dup.isPending;

  function fail(e: unknown) {
    const err = toAppError(e);
    if (err.code === "version_conflict") setConflict(true);
    else if (err.code === "order_not_paid") {
      // Директор может закрыть заказ без полной оплаты; менеджеру показываем остаток.
      if (isDirector) setDialog("force_close");
      else setError(cashErrorText(e));
    } else setError(stockErrorText(err, (id) => order.parts.find((p) => p.part_id === id)?.name) ?? orderErrorText(e));
  }

  /** Любое изменение заказа несёт текущую `version` (в теле; у DELETE — в query). */
  const run: Run = (c, done) => {
    setError(null);
    const req: OrderCall =
      c.method === "DELETE"
        ? { ...c, path: `${c.path}?version=${order.version}` }
        : { ...c, body: { ...c.body, version: order.version } };
    call.mutate(req, { onSuccess: () => done?.(), onError: fail });
  };

  const next = NEXT_STATUS[order.status];
  const nextAllowed = next && order.allowed_transitions.includes(next) ? next : null;
  const otherStatuses = order.allowed_transitions.filter((s) => s !== "cancelled" && s !== nextAllowed);
  const canCancel = order.allowed_transitions.includes("cancelled");
  const setStatus = (status: WorkOrderStatus) => run({ path: "/status", body: { status } });

  return (
    <div className="space-y-4">
      <Link to="/orders" className="text-sm text-muted underline">← Заказ-наряды</Link>

      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{order.number}</h1>
          <StatusBadge status={order.status} />
          <Badge>{ORDER_DEPARTMENT_LABELS[order.department]}</Badge>
          <PaymentBadge status={order.payment_status} />
          {order.is_overdue && <Badge tone="danger">Просрочен</Badge>}
        </div>
        <Stepper status={order.status} />
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
          <Row label="Клиент">
            <Link className="font-medium underline" to={`/clients/${encodeURIComponent(order.client.id)}`}>{order.client.full_name}</Link>{" "}
            <a className="underline" href={`tel:${normalizePhone(order.client.phone)}`}>{maskPhone(order.client.phone)}</a>
          </Row>
          <Row label="Автомобиль">
            <Link className="font-medium underline" to={`/vehicles/${encodeURIComponent(order.vehicle.id)}`}>
              {order.vehicle.plate_number || `${order.vehicle.make} ${order.vehicle.model}`}
            </Link>
            {order.vehicle.plate_number && <span className="text-muted"> {order.vehicle.make} {order.vehicle.model}</span>}
          </Row>
          <Row label="Пробег">{order.mileage_in !== null ? `${order.mileage_in.toLocaleString("ru-RU")} км` : "—"}</Row>
          <Row label="Срок готовности">
            <span className={clsx(order.is_overdue && "font-medium text-danger")}>{fmtDateTime(order.planned_ready_at, tz)}</span>
          </Row>
          <Row label="Ответственный">{order.manager.full_name}</Row>
          <Row label="Создан">{fmtDateTime(order.created_at, tz)}</Row>
          {order.cancel_reason && <Row label="Причина отмены">{order.cancel_reason}</Row>}
        </dl>
        {(order.complaint || order.intake_notes || order.diagnosis) && (
          <dl className="space-y-1 rounded-lg border border-border bg-surface p-3 text-sm">
            {order.complaint && <Row label="Жалоба">{order.complaint}</Row>}
            {order.intake_notes && <Row label="Состояние при приёме">{order.intake_notes}</Row>}
            {order.diagnosis && <Row label="Диагноз">{order.diagnosis}</Row>}
          </dl>
        )}
      </header>

      {error && !dialog && <Alert>{error}</Alert>}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <aside aria-label="Итоги заказа" className="order-first space-y-3 self-start rounded-lg border border-border bg-surface p-4 lg:sticky lg:top-4 lg:order-last">
          <dl className="space-y-1 text-sm">
            <Sum label="Работы" value={formatMoney(order.works_total)} />
            <Sum label="Запчасти" value={formatMoney(order.parts_total)} />
            <Sum label={`Скидка (${order.discount_percent.replace(/\.00$/, "")}%)`} value={`−${formatMoney(order.discount_total)}`} />
            <Sum label="Итого" value={formatMoney(order.total)} strong />
            <Sum label="Оплачено" value={formatMoney(order.paid_total)} />
            <Sum label="К оплате" value={formatMoney(order.balance_due)} />
          </dl>
          <div className="flex flex-col gap-2">
            {nextAllowed && (
              <Button loading={busy} onClick={() => setStatus(nextAllowed)}>
                Следующий статус: {STATUS_LABELS[nextAllowed]}
              </Button>
            )}
            {otherStatuses.length > 0 && (
              <Select label="Перевести в…" value="" disabled={busy} onChange={(e) => e.target.value && setStatus(e.target.value as WorkOrderStatus)}>
                <option value="">Выбрать статус</option>
                {otherStatuses.map((s) => (
                  <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                ))}
              </Select>
            )}
            <div className="flex gap-2">
              <LinkButton variant="secondary" className="flex-1" to={`/orders/${encodeURIComponent(order.id)}/print`}>Печать</LinkButton>
              <div className="relative">
                <Button variant="secondary" aria-label="Ещё" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((v) => !v)}>⋯</Button>
                {menu && (
                  <div role="menu" className="absolute bottom-full right-0 z-10 mb-1 w-52 rounded-lg border border-border bg-surface p-1 shadow-lg lg:bottom-auto lg:top-full lg:mb-0 lg:mt-1">
                    {!readOnly && (
                      <MenuItem onClick={() => { setMenu(false); setError(null); setDialog("edit"); }}>Править данные</MenuItem>
                    )}
                    <MenuItem
                      onClick={() => {
                        setMenu(false);
                        setError(null);
                        dup.mutate(undefined, { onSuccess: (o) => navigate(`/orders/${encodeURIComponent(o.id)}`), onError: fail });
                      }}
                    >
                      Дублировать
                    </MenuItem>
                    {canCancel && (
                      <MenuItem danger onClick={() => { setMenu(false); setError(null); setDialog("cancel"); }}>Отменить заказ</MenuItem>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </aside>

        <section className="min-w-0 space-y-3">
          <OrderPayments order={order} />
          <OrderPartRequests orderId={order.id} />
          <div role="tablist" aria-label="Разделы заказа" className="flex gap-1 overflow-x-auto border-b border-border">
            {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
              <button
                key={t}
                role="tab"
                type="button"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={clsx("min-h-10 whitespace-nowrap border-b-2 px-3 text-sm", tab === t ? "border-accent font-medium" : "border-transparent text-muted hover:text-fg")}
              >
                {TAB_LABELS[t]}
                {t === "works" && ` (${order.items.filter((i) => i.status !== "cancelled").length})`}
                {t === "parts" && ` (${order.parts.length})`}
              </button>
            ))}
          </div>
          <div role="tabpanel" aria-label={TAB_LABELS[tab]}>
            {tab === "works" && <WorksTab order={order} readOnly={readOnly} isDirector={isDirector} mechanics={mech.data} run={run} busy={busy} />}
            {tab === "parts" && <PartsTab order={order} readOnly={readOnly} isDirector={isDirector} run={run} busy={busy} />}
            {tab === "comments" && <CommentsTab orderId={order.id} />}
            {tab === "history" && <HistoryTab orderId={order.id} tz={tz} />}
          </div>
        </section>
      </div>

      {dialog === "cancel" && <CancelDialog busy={busy} error={error} onClose={() => setDialog(null)} onSubmit={(reason) => run({ path: "/status", body: { status: "cancelled", cancel_reason: reason } }, () => setDialog(null))} />}
      {dialog === "force_close" && (
        <ForceCloseDialog
          balanceDue={order.balance_due}
          onClose={() => setDialog(null)}
          submit={(comment) => call.mutateAsync({ path: "/status", body: { status: "closed", force_close: true, comment, version: order.version } })}
        />
      )}
      {dialog === "edit" && <EditDialog order={order} tz={tz} busy={busy} error={error} onClose={() => setDialog(null)} run={run} />}
      {conflict && (
        <ConflictDialog
          onRefresh={() => {
            setConflict(false);
            setError(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-32 shrink-0 text-muted">{label}</dt>
      <dd className="min-w-0 whitespace-pre-wrap break-words">{children}</dd>
    </div>
  );
}
function Sum({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={clsx("flex justify-between gap-2", strong && "border-t border-border pt-1 text-base font-semibold")}>
      <dt className={strong ? undefined : "text-muted"}>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
function MenuItem({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" role="menuitem" onClick={onClick} className={clsx("block min-h-10 w-full rounded px-3 text-left text-sm hover:bg-bg", danger && "text-danger")}>
      {children}
    </button>
  );
}

function Stepper({ status }: { status: WorkOrderStatus }) {
  if (status === "cancelled") return <p className="text-sm text-danger">Заказ отменён</p>;
  const idx = STATUS_ORDER.indexOf(status);
  return (
    <ol aria-label="Ход заказа" className="flex flex-wrap gap-1 text-xs">
      {STATUS_ORDER.map((s, i) => (
        <li
          key={s}
          aria-current={i === idx ? "step" : undefined}
          className={clsx(
            "rounded-full border px-2 py-0.5",
            i < idx && "border-success/40 text-success",
            i === idx && "border-accent bg-accent font-medium text-accent-fg",
            i > idx && "border-border text-muted",
          )}
        >
          {i < idx && <span aria-hidden="true">✓ </span>}
          {STATUS_LABELS[s]}
        </li>
      ))}
    </ol>
  );
}

/* ---------- Диалоги ---------- */

function CancelDialog({ busy, error, onClose, onSubmit }: { busy: boolean; error: string | null; onClose: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <Modal title="Отменить заказ" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (reason.trim()) onSubmit(reason.trim());
        }}
      >
        <Textarea label="Причина отмены" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} required />
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Назад</Button>
          <Button type="submit" variant="danger" loading={busy} disabled={!reason.trim()}>Подтвердить отмену</Button>
        </div>
      </form>
    </Modal>
  );
}

function EditDialog({ order, tz, busy, error, onClose, run }: { order: WorkOrder; tz: string; busy: boolean; error: string | null; onClose: () => void; run: Run }) {
  const [mileage, setMileage] = useState(order.mileage_in?.toString() ?? "");
  const [planned, setPlanned] = useState(isoToLocalInput(order.planned_ready_at, tz));
  const [complaint, setComplaint] = useState(order.complaint ?? "");
  const [intake, setIntake] = useState(order.intake_notes ?? "");
  const [diagnosis, setDiagnosis] = useState(order.diagnosis ?? "");
  const [discount, setDiscount] = useState(toInput(order.discount_percent));
  const [local, setLocal] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    if (!/^\d{0,7}$/.test(mileage.trim())) return setLocal("Пробег: целое число");
    const m = mileage.trim() === "" ? null : Number(mileage);
    if (m !== order.mileage_in) body.mileage_in = m;
    if (planned !== isoToLocalInput(order.planned_ready_at, tz)) {
      const iso = planned ? localInputToIso(planned, tz) : null;
      if (planned && !iso) return setLocal("Недопустимый срок готовности");
      body.planned_ready_at = iso;
    }
    const nn = (v: string) => (v.trim() === "" ? null : v.trim());
    if (nn(complaint) !== order.complaint) body.complaint = nn(complaint);
    if (nn(intake) !== order.intake_notes) body.intake_notes = nn(intake);
    if (nn(diagnosis) !== order.diagnosis) body.diagnosis = nn(diagnosis);
    const d = parseDecimal(discount, 2);
    if (d === null || Number(d) > 100) return setLocal("Скидка: число от 0 до 100");
    if (d !== order.discount_percent) body.discount_percent = d;
    setLocal(null);
    if (Object.keys(body).length === 0) return onClose();
    run({ path: "", method: "PATCH", body }, onClose);
  }

  return (
    <Modal title="Данные заказа" onClose={onClose} wide>
      <form className="space-y-3" onSubmit={submit}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Пробег, км" inputMode="numeric" value={mileage} onChange={(e) => setMileage(e.target.value)} />
          <Input label="Скидка заказа, %" inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} />
          <Input label="Срок готовности" type="datetime-local" value={planned} onChange={(e) => setPlanned(e.target.value)} />
        </div>
        <Textarea label="Жалоба" value={complaint} maxLength={2000} onChange={(e) => setComplaint(e.target.value)} />
        <Textarea label="Состояние при приёме" value={intake} maxLength={2000} onChange={(e) => setIntake(e.target.value)} />
        <Textarea label="Диагноз" value={diagnosis} maxLength={4000} onChange={(e) => setDiagnosis(e.target.value)} />
        {(local || error) && <Alert>{local ?? error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={busy}>Сохранить</Button>
        </div>
      </form>
    </Modal>
  );
}

/* ---------- Работы ---------- */

interface TabProps {
  order: WorkOrder;
  readOnly: boolean;
  isDirector: boolean;
  run: Run;
  busy: boolean;
}

function WorksTab({ order, readOnly, isDirector, mechanics, run, busy }: TabProps & { mechanics: MechanicRef[] | undefined }) {
  const [term, setTerm] = useState("");
  const dq = useDebounced(term.trim(), 300);
  const found = useCatalogServices(order.location_id, dq, !readOnly && dq.length >= 2);
  const [custom, setCustom] = useState(false);
  const items = order.items;
  // В статусе ready работы добавлять нельзя (контракт: 409 invalid_state).
  const canAdd = !readOnly && order.status !== "ready";

  return (
    <div className="space-y-3">
      {canAdd && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1">
              <Input label="Добавить работу из каталога" type="search" placeholder="Название услуги" value={term} onChange={(e) => setTerm(e.target.value)} />
            </div>
            <Button type="button" variant="secondary" onClick={() => setCustom((v) => !v)} aria-expanded={custom}>Произвольная работа</Button>
          </div>
          {dq.length >= 2 && (
            <ul aria-label="Результаты поиска услуг" className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
              {found.isLoading && <li className="px-3 py-2 text-muted">Поиск…</li>}
              {found.data?.items.length === 0 && <li className="px-3 py-2 text-muted">Ничего не найдено</li>}
              {found.data?.items.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => run({ path: "/items", body: { service_id: s.id } }, () => setTerm(""))}
                    className="flex min-h-10 w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-bg"
                  >
                    <span className="min-w-0 break-words">{s.name}</span>
                    <span className="shrink-0 text-muted">{formatMoney(s.price)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {custom && <CustomWorkForm busy={busy} run={run} onDone={() => setCustom(false)} />}
        </div>
      )}

      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Работ пока нет</p>
      ) : (
        <ul className="space-y-2">
          {items.map((it) => (
            <ItemRow key={it.id} item={it} orderId={order.id} version={order.version} readOnly={readOnly} isDirector={isDirector} mechanics={mechanics} run={run} busy={busy} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CustomWorkForm({ busy, run, onDone }: { busy: boolean; run: Run; onDone: () => void }) {
  const [name, setName] = useState("");
  const [dep, setDep] = useState<Department>("service");
  const [price, setPrice] = useState("");
  const [qty, setQty] = useState("1");
  const [hours, setHours] = useState("");
  const [err, setErr] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const p = parseDecimal(price, 2);
    const q = parseDecimal(qty, 2);
    const h = hours.trim() ? parseDecimal(hours, 2) : "0.00";
    if (!name.trim()) return setErr("Укажите название работы");
    if (p === null) return setErr("Цена: число не меньше 0, до двух знаков");
    if (q === null || Number(q) <= 0) return setErr("Количество: число больше 0");
    if (h === null) return setErr("Нормочасы: число не меньше 0");
    setErr(null);
    run({ path: "/items", body: { name: name.trim(), department: dep, unit_price: p, quantity: q, norm_hours: h } }, onDone);
  }

  return (
    <form onSubmit={submit} aria-label="Произвольная работа" className="grid gap-3 rounded-lg border border-border bg-surface p-3 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Input label="Название работы" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
      </div>
      <Select label="Отдел работы" value={dep} onChange={(e) => setDep(e.target.value as Department)}>
        {(Object.keys(DEPARTMENT_LABELS) as Department[]).map((d) => (
          <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
        ))}
      </Select>
      <Input label="Цена, ₽" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
      <Input label="Количество" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />
      <Input label="Нормочасы на единицу" inputMode="decimal" value={hours} onChange={(e) => setHours(e.target.value)} />
      {err && <div className="sm:col-span-2"><Alert>{err}</Alert></div>}
      <div className="flex justify-end gap-2 sm:col-span-2">
        <Button type="button" variant="secondary" onClick={onDone}>Отмена</Button>
        <Button type="submit" loading={busy}>Добавить работу</Button>
      </div>
    </form>
  );
}

const OPEN_ITEM: WorkOrderItem["status"][] = ["pending", "in_progress", "paused"];

function ItemRow({
  item,
  orderId,
  version,
  readOnly,
  isDirector,
  mechanics,
  run,
  busy,
}: {
  item: WorkOrderItem;
  orderId: string;
  version: number;
  readOnly: boolean;
  isDirector: boolean;
  mechanics: MechanicRef[] | undefined;
  run: Run;
  busy: boolean;
}) {
  const [confirm, setConfirm] = useState<null | "cancel" | "delete">(null);
  const cancelled = item.status === "cancelled";
  const started = item.status !== "pending";
  const catalog = item.service_id !== null;
  const lockEdit = readOnly || started;
  const lockPrice = lockEdit || (catalog && !isDirector);
  const base = `/items/${item.id}`;
  const patch = (body: Record<string, unknown>) => run({ path: base, method: "PATCH", body });
  const canMechanic = !readOnly && OPEN_ITEM.includes(item.status);
  const list = mechanics ?? [];
  const startedHint = "Работа начата — изменить нельзя";

  return (
    <li className={clsx("rounded-lg border border-border bg-surface p-3", cancelled && "opacity-60")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={clsx("break-words font-medium", cancelled && "line-through")}>{item.name}</p>
          <p className="text-xs text-muted">
            {DEPARTMENT_LABELS[item.department]} · норма {formatHours(item.norm_hours_total)} ·{" "}
            <span>
              <span aria-hidden="true">{ITEM_STATUS_GLYPH[item.status]}</span> {ITEM_STATUS_LABELS[item.status]}
            </span>
          </p>
        </div>
        <p className="font-medium">{formatMoney(item.total)}</p>
      </div>

      {!cancelled && (
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Field label="Кол-во">
            <DecimalField label={`Количество: ${item.name}`} value={item.quantity} disabled={lockEdit || busy} title={started ? startedHint : undefined} onCommit={(v) => patch({ quantity: v })} />
          </Field>
          <Field label="Цена">
            <DecimalField
              label={`Цена: ${item.name}`}
              value={item.unit_price}
              disabled={lockPrice || busy}
              title={started ? startedHint : catalog && !isDirector ? "Цену каталожной услуги меняет только руководитель" : undefined}
              onCommit={(v) => patch({ unit_price: v })}
            />
          </Field>
          <Field label="Скидка, %">
            <DecimalField label={`Скидка: ${item.name}`} value={item.discount_percent} max={100} disabled={lockEdit || busy} title={started ? startedHint : undefined} onCommit={(v) => patch({ discount_percent: v })} />
          </Field>
          <Field label="Механик">
            {canMechanic && list.length > 0 ? (
              <select
                aria-label={`Механик: ${item.name}`}
                value={item.mechanic?.id ?? ""}
                disabled={busy}
                onChange={(e) => patch({ mechanic_id: e.target.value || null })}
                className="min-h-9 w-full rounded border border-border bg-surface px-2 text-sm"
              >
                <option value="">Не назначен</option>
                {item.mechanic && !list.some((m) => m.id === item.mechanic?.id) && <option value={item.mechanic.id}>{item.mechanic.full_name}</option>}
                {list.map((m) => (
                  <option key={m.id} value={m.id}>{m.full_name}</option>
                ))}
              </select>
            ) : (
              <span className="block min-h-9 py-1.5 text-sm">{item.mechanic?.full_name ?? "Не назначен"}</span>
            )}
          </Field>
        </div>
      )}
      {started && !cancelled && !readOnly && <p className="mt-1 text-xs text-muted">{startedHint}: количество, цена и скидка заблокированы.</p>}

      {!readOnly && OPEN_ITEM.includes(item.status) && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {confirm ? (
            <>
              <span className="text-sm">{confirm === "cancel" ? "Отменить строку?" : "Удалить строку?"}</span>
              <Button
                variant="danger"
                loading={busy}
                onClick={() => {
                  const c = confirm;
                  setConfirm(null);
                  if (c === "cancel") run({ path: `${base}/cancel` });
                  else run({ path: base, method: "DELETE" });
                }}
              >
                Да
              </Button>
              <Button variant="secondary" onClick={() => setConfirm(null)}>Нет</Button>
            </>
          ) : (
            <>
              <Button
                variant="secondary"
                disabled={busy || !item.mechanic}
                title={item.mechanic ? undefined : "Сначала назначьте механика"}
                aria-label={`Завершить вручную: ${item.name}`}
                onClick={() => run({ path: `${base}/complete` })}
              >
                Завершить вручную
              </Button>
              <Button variant="ghost" disabled={busy} aria-label={`Отменить строку: ${item.name}`} onClick={() => setConfirm("cancel")}>Отменить строку</Button>
              {item.status === "pending" && (
                <Button variant="ghost" disabled={busy} aria-label={`Удалить строку: ${item.name}`} onClick={() => setConfirm("delete")}>Удалить</Button>
              )}
            </>
          )}
        </div>
      )}
      {!readOnly && item.status === "done" && <div className="mt-2"><ReopenItemButton orderId={orderId} itemId={item.id} version={version} /></div>}
    </li>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <span className="mb-0.5 block text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}

/* ---------- Запчасти ---------- */

function PartsTab({ order, readOnly, isDirector, run, busy }: TabProps) {
  const [term, setTerm] = useState("");
  const dq = useDebounced(term.trim(), 300);
  const found = useCatalogParts(dq, !readOnly && dq.length >= 2);
  const [picked, setPicked] = useState<{ id: string; name: string } | null>(null);
  const [qty, setQty] = useState("1");
  const [custom, setCustom] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function addPicked(e: React.FormEvent) {
    e.preventDefault();
    const q = parseDecimal(qty, 3);
    if (!picked || q === null || Number(q) <= 0) return setErr("Количество: число больше 0, до трёх знаков");
    setErr(null);
    run({ path: "/parts", body: { part_id: picked.id, quantity: q } }, () => {
      setPicked(null);
      setTerm("");
      setQty("1");
    });
  }

  return (
    <div className="space-y-3">
      {!readOnly && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1">
              <Input label="Добавить запчасть из справочника" type="search" placeholder="Название или артикул" value={term} onChange={(e) => setTerm(e.target.value)} />
            </div>
            <Button type="button" variant="secondary" onClick={() => setCustom((v) => !v)} aria-expanded={custom}>Произвольная запчасть</Button>
          </div>
          {dq.length >= 2 && !picked && (
            <ul aria-label="Результаты поиска запчастей" className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
              {found.data?.items.length === 0 && <li className="px-3 py-2 text-muted">Ничего не найдено</li>}
              {found.data?.items.map((p) => (
                <li key={p.id}>
                  <button type="button" onClick={() => setPicked({ id: p.id, name: p.name })} className="flex min-h-10 w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-bg">
                    <span className="min-w-0 break-words">{p.name} <span className="text-muted">{p.sku}</span></span>
                    <span className="shrink-0 text-muted">{formatMoney(p.sale_price)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {picked && (
            <form onSubmit={addPicked} className="flex flex-wrap items-end gap-2 rounded-lg border border-border bg-surface p-3" aria-label="Количество запчасти">
              <p className="w-full text-sm font-medium">{picked.name}</p>
              <Input label="Количество" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} className="w-28" />
              <Button type="submit" loading={busy}>Добавить запчасть</Button>
              <Button type="button" variant="secondary" onClick={() => setPicked(null)}>Отмена</Button>
              {err && <div className="w-full"><Alert>{err}</Alert></div>}
            </form>
          )}
          {custom && <CustomPartForm busy={busy} run={run} onDone={() => setCustom(false)} />}
        </div>
      )}

      {order.parts.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Запчастей нет</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Название</Th>
              <Th>Кол-во</Th>
              <Th>Цена</Th>
              <Th>Сумма</Th>
              <Th>Остаток</Th>
              <Th>Добавил</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {order.parts.map((p) => (
              <PartRow key={p.id} part={p} readOnly={readOnly} isDirector={isDirector} run={run} busy={busy} />
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}

function PartRow({ part, readOnly, isDirector, run, busy }: { part: WorkOrderPart; readOnly: boolean; isDirector: boolean; run: Run; busy: boolean }) {
  const base = `/parts/${part.id}`;
  const catalog = part.part_id !== null;
  return (
    <tr>
      <Td>
        <span className="break-words">{part.name}</span>
        {part.sku && <span className="block text-xs text-muted">{part.sku}</span>}
      </Td>
      <Td>
        {readOnly ? (
          `${part.quantity.replace(/\.?0+$/, "")} ${part.unit ?? ""}`
        ) : (
          <DecimalField label={`Количество: ${part.name}`} scale={3} value={part.quantity} disabled={busy} onCommit={(v) => run({ path: base, method: "PATCH", body: { quantity: v } })} />
        )}
      </Td>
      <Td>
        {readOnly || (catalog && !isDirector) ? (
          formatMoney(part.unit_price)
        ) : (
          <DecimalField label={`Цена: ${part.name}`} value={part.unit_price} disabled={busy} onCommit={(v) => run({ path: base, method: "PATCH", body: { unit_price: v } })} />
        )}
      </Td>
      <Td>{formatMoney(part.total)}</Td>
      <Td>
        {part.in_stock === null ? (
          "—"
        ) : (
          <span className={Number(part.in_stock) < Number(part.quantity) ? "font-medium text-danger" : undefined}>
            {Number(part.in_stock) < Number(part.quantity) && <span className="sr-only">Не хватает: </span>}
            {fmtQty(part.in_stock)}
          </span>
        )}
      </Td>
      <Td>{part.added_by.full_name}</Td>
      <Td>
        {!readOnly && (
          <Button variant="ghost" disabled={busy} aria-label={`Удалить запчасть: ${part.name}`} onClick={() => run({ path: base, method: "DELETE" })}>Удалить</Button>
        )}
      </Td>
    </tr>
  );
}

function CustomPartForm({ busy, run, onDone }: { busy: boolean; run: Run; onDone: () => void }) {
  const [name, setName] = useState("");
  const [qty, setQty] = useState("1");
  const [price, setPrice] = useState("");
  const [err, setErr] = useState<string | null>(null);
  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = parseDecimal(qty, 3);
    const p = parseDecimal(price, 2);
    if (!name.trim()) return setErr("Укажите название");
    if (q === null || Number(q) <= 0) return setErr("Количество: число больше 0, до трёх знаков");
    if (p === null) return setErr("Цена: число не меньше 0, до двух знаков");
    setErr(null);
    run({ path: "/parts", body: { name: name.trim(), quantity: q, unit_price: p } }, onDone);
  }
  return (
    <form onSubmit={submit} aria-label="Произвольная запчасть" className="grid gap-3 rounded-lg border border-border bg-surface p-3 sm:grid-cols-3">
      <div className="sm:col-span-3">
        <Input label="Название запчасти" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
      </div>
      <Input label="Количество" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />
      <Input label="Цена, ₽" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
      {err && <div className="sm:col-span-3"><Alert>{err}</Alert></div>}
      <div className="flex justify-end gap-2 sm:col-span-3">
        <Button type="button" variant="secondary" onClick={onDone}>Отмена</Button>
        <Button type="submit" loading={busy}>Добавить запчасть</Button>
      </div>
    </form>
  );
}

/* ---------- Комментарии и история ---------- */

function CommentsTab({ orderId }: { orderId: string }) {
  const [internal, setInternal] = useState(true);
  const q = useOrderComments(orderId, internal);
  const add = useAddComment(orderId);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const tz = useLocationTz(undefined);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setErr(null);
    add.mutate({ text: text.trim(), is_internal: internal }, { onSuccess: () => setText(""), onError: (x) => setErr(orderErrorText(x)) });
  }

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Тип комментариев" className="inline-flex overflow-hidden rounded border border-border">
        {[true, false].map((v) => (
          <button key={String(v)} type="button" aria-pressed={internal === v} onClick={() => setInternal(v)} className={clsx("min-h-10 px-3 text-sm", internal === v ? "bg-accent text-accent-fg" : "bg-surface hover:bg-bg")}>
            {v ? "Внутренние" : "Для клиента"}
          </button>
        ))}
      </div>
      {q.isLoading ? (
        <Skeleton lines={2} />
      ) : q.error ? (
        <LoadError error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data?.length ? (
        <ul className="space-y-2">
          {q.data.map((c) => (
            <li key={c.id} className="rounded-lg border border-border bg-surface p-3 text-sm">
              <p className="text-xs text-muted">{c.author.full_name} · {fmtDateTime(c.created_at, tz)}</p>
              <p className="mt-1 whitespace-pre-wrap break-words">{c.text}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Комментариев пока нет</p>
      )}
      <form onSubmit={submit} className="space-y-2">
        <Textarea label={internal ? "Внутренний комментарий" : "Комментарий для клиента"} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} />
        {err && <Alert>{err}</Alert>}
        <Button type="submit" loading={add.isPending} disabled={!text.trim()}>Отправить</Button>
      </form>
    </div>
  );
}

function HistoryTab({ orderId, tz }: { orderId: string; tz: string }) {
  const q = useOrderHistory(orderId);
  if (q.isLoading) return <Skeleton lines={3} />;
  if (q.error) return <LoadError error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data?.length) return <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">История пуста</p>;
  return (
    <ol className="space-y-2">
      {q.data.map((h) => (
        <li key={h.id} className="rounded-lg border border-border bg-surface p-3 text-sm">
          <p>
            {h.from_status ? `${STATUS_LABELS[h.from_status]} → ` : ""}
            <span className="font-medium">{STATUS_LABELS[h.to_status]}</span>
          </p>
          <p className="text-xs text-muted">{h.changed_by.full_name} · {fmtDateTime(h.created_at, tz)}</p>
          {h.comment && <p className="mt-1 break-words">{h.comment}</p>}
        </li>
      ))}
    </ol>
  );
}
