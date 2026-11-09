import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { type VehicleInput, useCreateVehicle, useUpdateVehicle, useVehicleById } from "@/features/clients/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import type { Vehicle } from "@/shared/api/types";
import { isValidVin, maskVin, normalizePlate } from "@/shared/lib/masks";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Input, LinkButton, Loading, Textarea } from "@/shared/ui/ui";

/** Добавление авто клиенту: /clients/:id/vehicles/new */
export function VehicleNewPage() {
  const { id } = useParams();
  return <VehicleForm clientId={id ?? ""} />;
}

/** Редактирование: /vehicles/:id/edit */
export function VehicleEditPage() {
  const { id } = useParams();
  const q = useVehicleById(id);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert>{toAppError(q.error).message}</Alert>;
  return <VehicleForm clientId={q.data.client_id} vehicle={q.data} />;
}

function DuplicateVin({ err }: { err: AppError }) {
  if (err.code !== "duplicate_vin") return null;
  const vid = err.details.existing_vehicle_id;
  return (
    <div role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
      {err.message}
      {vid && (
        <>
          {": "}
          <Link className="font-medium underline" to={`/vehicles/${encodeURIComponent(vid)}`}>открыть автомобиль</Link>
        </>
      )}
    </div>
  );
}

function intOrNull(s: string): number | null {
  const t = s.trim();
  return t === "" ? null : Number(t);
}

function VehicleForm({ clientId, vehicle }: { clientId: string; vehicle?: Vehicle }) {
  const nav = useNavigate();
  const toast = useToast();
  const create = useCreateVehicle(clientId);
  const update = useUpdateVehicle(vehicle?.id ?? "");
  const m = vehicle ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  const [make, setMake] = useState(vehicle?.make ?? "");
  const [model, setModel] = useState(vehicle?.model ?? "");
  const [year, setYear] = useState(vehicle?.year?.toString() ?? "");
  const [vin, setVin] = useState(vehicle?.vin ?? "");
  const [plate, setPlate] = useState(vehicle?.plate_number ?? "");
  const [color, setColor] = useState(vehicle?.color ?? "");
  const [mileage, setMileage] = useState(vehicle?.mileage?.toString() ?? "");
  const [notes, setNotes] = useState(vehicle?.notes ?? "");
  const [localErr, setLocalErr] = useState<Record<string, string>>({});

  const srv = (name: string) => (err?.code === "validation_error" ? fieldMessage(err, name) : undefined);
  const showAlert = err && err.code !== "validation_error" && err.code !== "duplicate_vin";
  const back = vehicle ? `/vehicles/${encodeURIComponent(vehicle.id)}` : `/clients/${encodeURIComponent(clientId)}`;

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    const y = intOrNull(year);
    const mi = intOrNull(mileage);
    const maxYear = new Date().getFullYear() + 1;
    if (!make.trim()) le.make = "Обязательное поле";
    if (!model.trim()) le.model = "Обязательное поле";
    if (y !== null && (!Number.isInteger(y) || y < 1900 || y > maxYear)) le.year = `Год: от 1900 до ${maxYear}`;
    if (vin && !isValidVin(vin)) le.vin = "VIN: 17 символов, без букв I, O, Q";
    if (mi !== null && (!Number.isInteger(mi) || mi < 0)) le.mileage = "Пробег: целое число от 0";
    setLocalErr(le);
    if (Object.keys(le).length) return;

    const body: VehicleInput = {
      make: make.trim(),
      model: model.trim(),
      year: y,
      vin: vin || null,
      plate_number: plate || null,
      color: color.trim() || null,
      mileage: mi,
      notes: notes.trim() || null,
    };
    if (vehicle) {
      update.mutate(body, {
        onSuccess: () => {
          toast.push("success", "Сохранено");
          nav(back);
        },
      });
    } else {
      create.mutate(body, { onSuccess: () => nav(back, { replace: true }) });
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{vehicle ? "Редактирование автомобиля" : "Новый автомобиль"}</h1>
        <LinkButton to={back} variant="secondary">Отмена</LinkButton>
      </div>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Марка" value={make} onChange={(e) => setMake(e.target.value)} error={localErr.make ?? srv("make")} />
          <Input label="Модель" value={model} onChange={(e) => setModel(e.target.value)} error={localErr.model ?? srv("model")} />
          <Input label="Год выпуска" inputMode="numeric" maxLength={4} value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, ""))} error={localErr.year ?? srv("year")} />
          <Input label="Цвет" value={color} onChange={(e) => setColor(e.target.value)} error={srv("color")} />
        </div>
        <Input label="VIN" autoCapitalize="characters" autoComplete="off" spellCheck={false} placeholder="17 символов" value={vin} onChange={(e) => setVin(maskVin(e.target.value))} error={localErr.vin ?? srv("vin")} />
        <Input label="Госномер" autoCapitalize="characters" autoComplete="off" spellCheck={false} placeholder="А123ВС777" value={plate} onChange={(e) => setPlate(normalizePlate(e.target.value))} error={srv("plate_number")} />
        <Input label="Пробег, км" inputMode="numeric" value={mileage} onChange={(e) => setMileage(e.target.value.replace(/\D/g, ""))} error={localErr.mileage ?? srv("mileage")} />
        <Textarea label="Заметки" value={notes} onChange={(e) => setNotes(e.target.value)} error={srv("notes")} />
        {err && <DuplicateVin err={err} />}
        {showAlert && <Alert>{err.message}</Alert>}
        <Button type="submit" loading={m.isPending} className="w-full sm:w-auto">{vehicle ? "Сохранить" : "Добавить"}</Button>
      </form>
    </div>
  );
}
