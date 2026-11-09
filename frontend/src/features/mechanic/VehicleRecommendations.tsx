import clsx from "clsx";
import { type FormEvent, useState } from "react";

import { useEntityOrders } from "@/features/orders/api";
import type { WorkOrderListItem } from "@/features/orders/types";
import { api } from "@/shared/api/client";
import { toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS, type Department } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Dialog, Input, Select, Textarea } from "@/shared/ui/ui";

import { mechanicErrorText, useCreateRecommendation, usePatchRecommendation, useVehicleRecommendations } from "./api";
import { formatDateTime } from "./time";
import { PRIORITY_LABELS, type Priority, type VehicleRecommendation } from "./types";

const PRIORITY_TONE = { low: "neutral", medium: "warning", high: "danger" } as const;
const CLOSED = new Set(["closed", "cancelled", "ready"]);

/** MG-10: блок «Рекомендации механиков» на карточке автомобиля. */
export function VehicleRecommendations({ vehicleId }: { vehicleId: string }) {
  const q = useVehicleRecommendations(vehicleId, "open");
  const patch = usePatchRecommendation(vehicleId);
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [toOrder, setToOrder] = useState<VehicleRecommendation | null>(null);
  const [error, setError] = useState<string | null>(null);

  function setStatus(r: VehicleRecommendation, status: "done" | "declined") {
    setError(null);
    patch.mutate(
      { id: r.id, body: { status } },
      {
        onSuccess: () => toast.push("success", status === "done" ? "Отмечено выполненным" : "Рекомендация отклонена"),
        onError: (e) => setError(mechanicErrorText(e)),
      },
    );
  }

  return (
    <div className="space-y-3">
      {error && <Alert>{error}</Alert>}
      {q.isLoading && <p role="status" className="text-sm text-muted">Загрузка…</p>}
      {q.isError && (
        <div role="alert" className="space-y-2">
          <p className="text-sm text-muted">Не удалось загрузить рекомендации</p>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      )}
      {q.data && q.data.length === 0 && <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Открытых рекомендаций нет</p>}
      {q.data && q.data.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {q.data.map((r) => (
            <li key={r.id} className="space-y-2 p-3" data-recommendation={r.id}>
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 whitespace-pre-wrap break-words text-sm">{r.text}</p>
                <Badge tone={PRIORITY_TONE[r.priority]}>{PRIORITY_LABELS[r.priority]}</Badge>
              </div>
              <div className="text-xs text-muted">
                {r.created_by.full_name} · {formatDateTime(r.created_at)}
                {r.work_order_number ? ` · заказ ${r.work_order_number}` : ""}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => setToOrder(r)}>Добавить в заказ</Button>
                <Button variant="secondary" disabled={patch.isPending} onClick={() => setStatus(r, "done")}>Выполнено</Button>
                <Button variant="ghost" disabled={patch.isPending} onClick={() => setStatus(r, "declined")}>Отклонить</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Button variant="secondary" onClick={() => setAdding(true)}>Добавить рекомендацию</Button>
      {adding && <AddDialog vehicleId={vehicleId} onClose={() => setAdding(false)} />}
      {toOrder && <ToOrderDialog vehicleId={vehicleId} rec={toOrder} onClose={() => setToOrder(null)} />}
    </div>
  );
}

function AddDialog({ vehicleId, onClose }: { vehicleId: string; onClose: () => void }) {
  const create = useCreateRecommendation(vehicleId);
  const toast = useToast();
  const [text, setText] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return setFieldErr("Рекомендация: от 1 до 1000 символов");
    setFieldErr(undefined);
    setError(null);
    create.mutate(
      { text: t, priority },
      {
        onSuccess: () => { toast.push("success", "Рекомендация добавлена"); onClose(); },
        onError: (e2) => (toAppError(e2).fields.text ? setFieldErr("Рекомендация: от 1 до 1000 символов") : setError(mechanicErrorText(e2))),
      },
    );
  }

  return (
    <Dialog open title="Новая рекомендация" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Textarea label="Что рекомендуете" rows={4} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} error={fieldErr} />
        <Select label="Приоритет" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
          {(Object.keys(PRIORITY_LABELS) as Priority[]).map((p) => <option key={p} value={p}>{PRIORITY_LABELS[p]}</option>)}
        </Select>
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={create.isPending}>Добавить</Button>
        </div>
      </form>
    </Dialog>
  );
}

/** «Добавить в заказ»: работа создаётся в открытом заказе авто (модуль 5), затем рекомендация получает done + work_order_id. */
function ToOrderDialog({ vehicleId, rec, onClose }: { vehicleId: string; rec: VehicleRecommendation; onClose: () => void }) {
  const orders = useEntityOrders("vehicles", vehicleId, 0, 50);
  const patch = usePatchRecommendation(vehicleId);
  const toast = useToast();
  const [orderId, setOrderId] = useState("");
  const [name, setName] = useState(rec.text.slice(0, 200));
  const [price, setPrice] = useState("");
  const [dept, setDept] = useState<Department>("service");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const open: WorkOrderListItem[] = (orders.data?.items ?? []).filter((o) => !CLOSED.has(o.status));
  const selected = open.find((o) => o.id === (orderId || open[0]?.id));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Укажите название работы (до 200 символов)";
    const p = parseDecimal(price, 2);
    if (!p) errs.unit_price = "Цена: число не меньше 0, до двух знаков после запятой";
    setErrors(errs);
    setError(null);
    if (Object.keys(errs).length || !selected) return;
    setBusy(true);
    try {
      await api(`/work-orders/${encodeURIComponent(selected.id)}/items`, {
        body: { version: selected.version, name: name.trim(), department: dept, unit_price: p },
      });
      await patch.mutateAsync({ id: rec.id, body: { status: "done", work_order_id: selected.id } });
      toast.push("success", `Работа добавлена в заказ ${selected.number}`);
      onClose();
    } catch (e2) {
      const err = toAppError(e2);
      const f: Record<string, string> = {};
      if (err.fields.name) f.name = "Укажите название работы (до 200 символов)";
      if (err.fields.unit_price) f.unit_price = "Цена: число не меньше 0, до двух знаков после запятой";
      setErrors(f);
      if (Object.keys(f).length === 0) setError(mechanicErrorText(e2));
      void orders.refetch();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title="Добавить в заказ" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="space-y-3" noValidate>
        {orders.isLoading && <p role="status" className="text-sm text-muted">Загрузка заказов…</p>}
        {orders.data && open.length === 0 && <p className="text-sm text-muted">У автомобиля нет открытых заказов. Создайте заказ и вернитесь к рекомендации.</p>}
        {open.length > 0 && (
          <>
            <Select label="Заказ" value={selected?.id ?? ""} onChange={(e) => setOrderId(e.target.value)}>
              {open.map((o) => <option key={o.id} value={o.id}>{o.number}</option>)}
            </Select>
            <Input label="Название работы" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} error={errors.name} />
            <Input label="Цена, ₽" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} error={errors.unit_price} />
            <Select label="Отдел" value={dept} onChange={(e) => setDept(e.target.value as Department)}>
              {(Object.keys(DEPARTMENT_LABELS) as Department[]).map((d) => <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>)}
            </Select>
          </>
        )}
        {error && <Alert>{error}</Alert>}
        <div className={clsx("flex justify-end gap-2")}>
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          {open.length > 0 && <Button type="submit" loading={busy}>Добавить</Button>}
        </div>
      </form>
    </Dialog>
  );
}
