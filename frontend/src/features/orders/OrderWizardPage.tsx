import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { ClientVehiclePicker, type PickedClient } from "@/features/appointments/ClientVehiclePicker";
import { useClientById } from "@/features/clients/api";
import { useActiveLocation } from "@/features/locations/api";
import { useDebounced } from "@/pages/catalog/common";
import { api } from "@/shared/api/client";
import { toAppError } from "@/shared/api/errors";
import { type Appointment, DEPARTMENT_LABELS, type Department } from "@/shared/api/types";
import { formatMoney, parseDecimal } from "@/shared/lib/money";
import { Alert, Button, Input, Select, Textarea } from "@/shared/ui/ui";

import { type OrderCreate, orderErrorText, useCatalogServices, useCreateOrder, useLocationTz, useMechanics } from "./api";
import { LoadError, Skeleton, localInputToIso } from "./ui";

interface Draft {
  key: string;
  service_id: string | null;
  name: string;
  price: string;
  quantity: string;
  department: Department;
  mechanic_id: string;
}

let seq = 0;
const nextKey = () => `d${++seq}`;

/** MG-06: создание заказ-наряда одной формой (в том числе из записи). */
export function OrderWizardPage() {
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const appointmentId = sp.get("appointment_id") ?? "";
  const qClient = sp.get("client_id") ?? "";
  const qVehicle = sp.get("vehicle_id") ?? "";

  const loc = useActiveLocation();
  const apt = useQuery({
    queryKey: ["appointments", "one", appointmentId],
    queryFn: () => api<Appointment>(`/appointments/${encodeURIComponent(appointmentId)}`),
    enabled: !!appointmentId,
  });
  const preClient = useClientById(!appointmentId && qClient ? qClient : undefined);

  const [pickedLoc, setPickedLoc] = useState("");
  const locationId = apt.data?.location_id ?? (pickedLoc || (loc.value !== "all" ? loc.value : (loc.items[0]?.id ?? "")));
  const tz = useLocationTz(locationId);
  const mech = useMechanics(locationId);
  const mechanics = mech.data ?? [];

  const [client, setClient] = useState<PickedClient | null>(null);
  const [vehicleId, setVehicleId] = useState("");
  const [mileage, setMileage] = useState("");
  const [complaint, setComplaint] = useState("");
  const [intake, setIntake] = useState("");
  const [planned, setPlanned] = useState("");
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [fieldErr, setFieldErr] = useState<Record<string, string>>({});
  const create = useCreateOrder();

  // Подстановка из записи (клиент, авто, услуги) и из ?client_id=&vehicle_id=.
  // Состояние выставляется во время рендера (а не в useEffect), чтобы форма не показывалась
  // ни на один кадр с клиентом из записи, но без её услуг (кнопка «Создать заказ» уже активна).
  const [prefilled, setPrefilled] = useState(false);
  if (!prefilled && apt.data) {
    const a = apt.data;
    setPrefilled(true);
    setClient({ id: a.client.id, full_name: a.client.full_name, phone: a.client.phone });
    setVehicleId(a.vehicle_id);
    setDrafts(
      a.services.map((s) => ({ key: nextKey(), service_id: s.id, name: s.name, price: "", quantity: "1.00", department: a.department, mechanic_id: "" })),
    );
  } else if (!prefilled && preClient.data) {
    const c = preClient.data;
    setPrefilled(true);
    setClient({ id: c.id, full_name: c.full_name, phone: c.phone });
    if (qVehicle) setVehicleId(qVehicle);
  }

  const locked = !!appointmentId;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const fe: Record<string, string> = {};
    if (!locationId) fe.location = "Выберите точку";
    if (!client) fe.client = "Выберите клиента";
    if (!vehicleId) fe.vehicle = "Выберите автомобиль";
    if (mileage.trim() && !/^\d{1,7}$/.test(mileage.trim())) fe.mileage = "Пробег: целое число";
    let plannedIso: string | null = null;
    if (planned) {
      plannedIso = localInputToIso(planned, tz);
      if (!plannedIso) fe.planned = "Недопустимая дата";
    }
    const items: Record<string, unknown>[] = [];
    for (const d of drafts) {
      const q = parseDecimal(d.quantity, 2);
      if (q === null || Number(q) <= 0) {
        fe.items = `Количество «${d.name}»: число больше 0`;
        break;
      }
      const base: Record<string, unknown> = { quantity: q };
      if (d.mechanic_id) base.mechanic_id = d.mechanic_id;
      if (d.service_id) items.push({ service_id: d.service_id, ...base });
      else {
        const p = parseDecimal(d.price, 2);
        if (p === null) {
          fe.items = `Цена «${d.name}»: число не меньше 0`;
          break;
        }
        items.push({ name: d.name, department: d.department, unit_price: p, ...base });
      }
    }
    setFieldErr(fe);
    setErr(null);
    if (Object.keys(fe).length || !client) return;

    const body: OrderCreate = { location_id: locationId, client_id: client.id, vehicle_id: vehicleId };
    if (appointmentId) body.appointment_id = appointmentId;
    if (mileage.trim()) body.mileage_in = Number(mileage);
    if (complaint.trim()) body.complaint = complaint.trim();
    if (intake.trim()) body.intake_notes = intake.trim();
    if (plannedIso) body.planned_ready_at = plannedIso;
    if (items.length) body.items = items;

    create.mutate(body, {
      onSuccess: (o) => navigate(`/orders/${encodeURIComponent(o.id)}`),
      onError: (x) => {
        const ae = toAppError(x);
        if (ae.code === "appointment_has_order" && ae.details.work_order_id) {
          navigate(`/orders/${encodeURIComponent(ae.details.work_order_id)}`);
          return;
        }
        if (ae.code === "validation_error") setFieldErr((p) => ({ ...p, ...ae.fields }));
        setErr(orderErrorText(x));
      },
    });
  }

  if (appointmentId && apt.isLoading) return <Skeleton lines={5} />;
  if (appointmentId && apt.error) return <LoadError error={apt.error} onRetry={() => void apt.refetch()} />;

  return (
    <form onSubmit={submit} className="mx-auto max-w-3xl space-y-5" aria-label="Новый заказ-наряд">
      <Link to="/orders" className="inline-flex items-center gap-1 text-sm text-muted underline"><ArrowLeft aria-hidden="true" className="size-4" />Заказ-наряды</Link>
      <h1 className="text-xl font-semibold">Новый заказ</h1>

      {apt.data && (
        <p className="rounded-lg border border-border bg-surface p-3 text-sm">
          Заказ создаётся из записи: клиент, автомобиль и услуги подставлены{apt.data.work_order_number ? ` (уже есть заказ ${apt.data.work_order_number})` : ""}.
        </p>
      )}

      {!locked && loc.items.length > 1 && (loc.isDirector && loc.value === "all") && (
        <Select label="Точка" value={locationId} onChange={(e) => setPickedLoc(e.target.value)} error={fieldErr.location}>
          {loc.items.map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </Select>
      )}

      {locked ? (
        <section aria-label="Клиент и автомобиль" className="space-y-1 rounded-lg border border-border bg-surface p-3 text-sm">
          <p><span className="text-muted">Клиент: </span><span className="font-medium">{apt.data?.client.full_name}</span></p>
          <p>
            <span className="text-muted">Автомобиль: </span>
            <span className="font-medium">{apt.data?.vehicle.plate_number || `${apt.data?.vehicle.make} ${apt.data?.vehicle.model}`}</span>
          </p>
        </section>
      ) : (
        <ClientVehiclePicker client={client} onClient={setClient} vehicleId={vehicleId} onVehicle={setVehicleId} clientError={fieldErr.client} vehicleError={fieldErr.vehicle} />
      )}

      <fieldset className="space-y-3">
        <legend className="mb-1 text-sm font-medium">Приём</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Пробег, км" inputMode="numeric" value={mileage} onChange={(e) => setMileage(e.target.value)} error={fieldErr.mileage ?? fieldErr.mileage_in} />
          <Input label="Срок готовности" type="datetime-local" value={planned} onChange={(e) => setPlanned(e.target.value)} error={fieldErr.planned ?? fieldErr.planned_ready_at} />
        </div>
        <Textarea label="Жалоба клиента" value={complaint} maxLength={2000} onChange={(e) => setComplaint(e.target.value)} />
        <Textarea label="Состояние при приёме" value={intake} maxLength={2000} onChange={(e) => setIntake(e.target.value)} />
      </fieldset>

      <WorksPicker locationId={locationId} drafts={drafts} setDrafts={setDrafts} mechanics={mechanics.map((m) => ({ id: m.id, name: m.full_name }))} error={fieldErr.items} />

      {err && <Alert>{err}</Alert>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={() => navigate("/orders")}>Отмена</Button>
        <Button type="submit" loading={create.isPending}>Создать заказ</Button>
      </div>
    </form>
  );
}

function WorksPicker({
  locationId,
  drafts,
  setDrafts,
  mechanics,
  error,
}: {
  locationId: string;
  drafts: Draft[];
  setDrafts: (f: (d: Draft[]) => Draft[]) => void;
  mechanics: { id: string; name: string }[];
  error?: string;
}) {
  const [term, setTerm] = useState("");
  const dq = useDebounced(term.trim(), 300);
  const found = useCatalogServices(locationId, dq, dq.length >= 2);
  const [custom, setCustom] = useState(false);
  const [cName, setCName] = useState("");
  const [cPrice, setCPrice] = useState("");
  const [cErr, setCErr] = useState<string | null>(null);

  const patch = (key: string, p: Partial<Draft>) => setDrafts((d) => d.map((x) => (x.key === key ? { ...x, ...p } : x)));

  function addCustom() {
    const p = parseDecimal(cPrice, 2);
    if (!cName.trim()) return setCErr("Укажите название работы");
    if (p === null) return setCErr("Цена: число не меньше 0");
    setCErr(null);
    setDrafts((d) => [...d, { key: nextKey(), service_id: null, name: cName.trim(), price: p, quantity: "1.00", department: "service", mechanic_id: "" }]);
    setCName("");
    setCPrice("");
    setCustom(false);
  }

  return (
    <fieldset className="space-y-3">
      <legend className="mb-1 text-sm font-medium">Работы</legend>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <Input label="Добавить работу из каталога" type="search" placeholder="Название услуги" value={term} onChange={(e) => setTerm(e.target.value)} />
        </div>
        <Button type="button" variant="secondary" aria-expanded={custom} onClick={() => setCustom((v) => !v)}>Произвольная работа</Button>
      </div>
      {dq.length >= 2 && (
        <ul aria-label="Результаты поиска услуг" className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
          {found.isLoading && <li className="px-3 py-2 text-muted">Поиск…</li>}
          {found.data?.items.length === 0 && <li className="px-3 py-2 text-muted">Ничего не найдено</li>}
          {found.data?.items.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => {
                  setDrafts((d) => [...d, { key: nextKey(), service_id: s.id, name: s.name, price: s.price, quantity: "1.00", department: s.department, mechanic_id: "" }]);
                  setTerm("");
                }}
                className="flex min-h-10 w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-bg"
              >
                <span className="min-w-0 break-words">{s.name}</span>
                <span className="shrink-0 text-muted">{formatMoney(s.price)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {custom && (
        <div className="grid gap-3 rounded-lg border border-border bg-surface p-3 sm:grid-cols-[1fr_8rem_auto] sm:items-end">
          <Input label="Название работы" value={cName} maxLength={200} onChange={(e) => setCName(e.target.value)} />
          <Input label="Цена, ₽" inputMode="decimal" value={cPrice} onChange={(e) => setCPrice(e.target.value)} />
          <Button type="button" onClick={addCustom}>Добавить работу</Button>
          {cErr && <div className="sm:col-span-3"><Alert>{cErr}</Alert></div>}
        </div>
      )}

      {drafts.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Работ пока нет — их можно добавить и после создания заказа</p>
      ) : (
        <ul className="space-y-2" aria-label="Работы заказа">
          {drafts.map((d) => (
            <li key={d.key} className="rounded-lg border border-border bg-surface p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="break-words font-medium">{d.name}</p>
                  <p className="text-xs text-muted">{d.price ? formatMoney(d.price) : "Цена по каталогу"} · {DEPARTMENT_LABELS[d.department]}</p>
                </div>
                <Button type="button" variant="ghost" aria-label={`Убрать: ${d.name}`} onClick={() => setDrafts((x) => x.filter((y) => y.key !== d.key))}>Убрать</Button>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Input label="Количество" inputMode="decimal" value={d.quantity} onChange={(e) => patch(d.key, { quantity: e.target.value })} />
                {mechanics.length > 0 && (
                  <Select label="Механик" value={d.mechanic_id} onChange={(e) => patch(d.key, { mechanic_id: e.target.value })}>
                    <option value="">Не назначен</option>
                    {mechanics.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </Select>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {error && <Alert>{error}</Alert>}
    </fieldset>
  );
}
