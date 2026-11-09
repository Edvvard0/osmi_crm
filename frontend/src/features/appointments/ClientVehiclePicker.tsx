import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { type ClientInput, useClientById, useCreateClient } from "@/features/clients/api";
import { DuplicateNotice } from "@/pages/clients/ClientFormPage";
import { useDebounced } from "@/pages/catalog/common";
import { api } from "@/shared/api/client";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import type { Client, Page, Vehicle } from "@/shared/api/types";
import { maskPhone, normalizePhone, normalizePlate } from "@/shared/lib/masks";
import { Alert, Button, Input, Select } from "@/shared/ui/ui";

export interface PickedClient {
  id: string;
  full_name: string;
  phone: string;
}

function useClientSearch(term: string) {
  return useQuery({
    queryKey: ["clients", "pick", term],
    queryFn: () => api<Page<Client>>(`/clients?${new URLSearchParams({ search: term, limit: "8", archived: "false" }).toString()}`),
    enabled: term.length >= 2,
  });
}

interface VehicleDraft {
  make: string;
  model: string;
  plate: string;
}

function useCreateVehicleFor() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { clientId: string } & VehicleDraft) =>
      api<Vehicle>(`/clients/${encodeURIComponent(v.clientId)}/vehicles`, {
        body: { make: v.make.trim(), model: v.model.trim(), year: null, vin: null, plate_number: v.plate || null, color: null, mileage: null, notes: null },
      }),
  });
}

const PHONE_HINT = "Введите номер полностью: +7 (999) 123-45-67";

interface Props {
  client: PickedClient | null;
  onClient: (c: PickedClient | null) => void;
  vehicleId: string;
  onVehicle: (id: string) => void;
  clientError?: string;
  vehicleError?: string;
}

/**
 * Выбор клиента поиском и его авто. Нового клиента и авто можно создать прямо здесь:
 * сначала POST /clients, затем POST /clients/{id}/vehicles. Если авто не создалось, клиент уже выбран и повторяется только второй шаг.
 */
export function ClientVehiclePicker({ client, onClient, vehicleId, onVehicle, clientError, vehicleError }: Props) {
  const [input, setInput] = useState("");
  const term = useDebounced(input.trim(), 300);
  const found = useClientSearch(client ? "" : term);
  const detail = useClientById(client?.id);
  const createClient = useCreateClient();
  const createVehicle = useCreateVehicleFor();

  const [mode, setMode] = useState<"none" | "newClient" | "newVehicle">("none");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [veh, setVeh] = useState<VehicleDraft>({ make: "", model: "", plate: "" });
  const [created, setCreated] = useState<Vehicle[]>([]);
  const [localErr, setLocalErr] = useState<Record<string, string>>({});
  const [stepErr, setStepErr] = useState<AppError | null>(null);

  const fetched = (detail.data?.vehicles ?? []).filter((v) => !v.archived_at);
  const vehicles = [...fetched, ...created.filter((c) => c.client_id === client?.id && !fetched.some((f) => f.id === c.id))];
  const needVehicleForm = !!client && mode === "none" && detail.isSuccess && vehicles.length === 0;
  const showVehicleForm = mode === "newVehicle" || needVehicleForm;

  // У клиента одно авто — подставляем его сразу (один раз на выбранного клиента, ручной выбор не перебиваем).
  const autoPicked = useRef<string | null>(null);
  const onlyVehicleId = fetched.length === 1 ? fetched[0]?.id : undefined;
  useEffect(() => {
    if (!client || !onlyVehicleId || vehicleId || autoPicked.current === client.id) return;
    autoPicked.current = client.id;
    onVehicle(onlyVehicleId);
  }, [client, onlyVehicleId, vehicleId, onVehicle]);

  function reset() {
    setMode("none");
    setName("");
    setPhone("");
    setVeh({ make: "", model: "", plate: "" });
    setLocalErr({});
    setStepErr(null);
  }

  function pick(c: PickedClient) {
    autoPicked.current = null;
    onClient(c);
    onVehicle("");
    setCreated([]);
    setInput("");
    reset();
  }

  function validateVehicle(le: Record<string, string>) {
    if (!veh.make.trim()) le.make = "Обязательное поле";
    if (!veh.model.trim()) le.model = "Обязательное поле";
  }

  async function submitVehicle(clientId: string) {
    try {
      const v = await createVehicle.mutateAsync({ clientId, ...veh, make: veh.make, model: veh.model });
      setCreated((x) => [...x, v]);
      onVehicle(v.id);
      reset();
    } catch (e) {
      setStepErr(toAppError(e));
      setMode("newVehicle");
    }
  }

  async function submitNew() {
    setStepErr(null);
    const le: Record<string, string> = {};
    const p = normalizePhone(phone);
    if (!name.trim()) le.full_name = "Обязательное поле";
    if (!p) le.phone = phone ? PHONE_HINT : "Обязательное поле";
    validateVehicle(le);
    setLocalErr(le);
    if (Object.keys(le).length || !p) return;
    const body: ClientInput = {
      client_type: "person",
      full_name: name.trim(),
      company_name: null,
      inn: null,
      phone: p,
      phone_extra: null,
      email: null,
      source: null,
      discount_percent: 0,
      notes: null,
    };
    let c: Client;
    try {
      c = await createClient.mutateAsync(body);
    } catch (e) {
      setStepErr(toAppError(e));
      return;
    }
    onClient({ id: c.id, full_name: c.full_name, phone: c.phone });
    setCreated([]);
    await submitVehicle(c.id);
  }

  async function submitVehicleOnly() {
    setStepErr(null);
    const le: Record<string, string> = {};
    validateVehicle(le);
    setLocalErr(le);
    if (Object.keys(le).length || !client) return;
    await submitVehicle(client.id);
  }

  const srv = (n: string) => (stepErr?.code === "validation_error" ? fieldMessage(stepErr, n) : undefined);
  const busy = createClient.isPending || createVehicle.isPending;

  const vehicleFields = (
    <div className="grid gap-3 sm:grid-cols-3">
      <Input id="qv-make" label="Марка" value={veh.make} onChange={(e) => setVeh({ ...veh, make: e.target.value })} error={localErr.make ?? srv("make")} />
      <Input id="qv-model" label="Модель" value={veh.model} onChange={(e) => setVeh({ ...veh, model: e.target.value })} error={localErr.model ?? srv("model")} />
      <Input id="qv-plate" label="Госномер" autoComplete="off" spellCheck={false} placeholder="А123ВС777" value={veh.plate} onChange={(e) => setVeh({ ...veh, plate: normalizePlate(e.target.value) })} error={srv("plate_number")} />
    </div>
  );

  return (
    <fieldset className="space-y-3">
      <legend className="mb-1 text-sm font-medium">Клиент и автомобиль</legend>

      {!client && mode !== "newClient" && (
        <div className="space-y-2">
          <Input
            id="apt-client-search"
            label="Поиск клиента"
            type="search"
            autoComplete="off"
            placeholder="ФИО, телефон, госномер"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            error={clientError}
          />
          {term.length >= 2 && (
            <ul aria-label="Найденные клиенты" className="divide-y divide-border rounded border border-border">
              {found.isLoading && <li className="px-3 py-2 text-sm text-muted">Поиск…</li>}
              {found.isError && <li className="px-3 py-2 text-sm text-danger">{toAppError(found.error).message}</li>}
              {found.data?.items.length === 0 && <li className="px-3 py-2 text-sm text-muted">Никого не найдено</li>}
              {found.data?.items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => pick({ id: c.id, full_name: c.full_name, phone: c.phone })}
                    className="flex min-h-10 w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-border/40"
                  >
                    <span className="truncate font-medium">{c.full_name}</span>
                    <span className="shrink-0 text-muted">{maskPhone(c.phone)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Button type="button" variant="secondary" onClick={() => setMode("newClient")}>+ Новый клиент</Button>
        </div>
      )}

      {!client && mode === "newClient" && (
        <div className="space-y-3 rounded border border-border p-3">
          <div className="text-sm font-medium">Новый клиент и автомобиль</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input id="qc-name" label="ФИО" value={name} onChange={(e) => setName(e.target.value)} error={localErr.full_name ?? srv("full_name")} />
            <Input id="qc-phone" label="Телефон" type="tel" inputMode="tel" autoComplete="off" placeholder="+7 (999) 123-45-67" value={phone} onChange={(e) => setPhone(maskPhone(e.target.value))} error={localErr.phone ?? srv("phone")} />
          </div>
          {vehicleFields}
          {stepErr && <DuplicateNotice err={stepErr} />}
          {stepErr && stepErr.code !== "validation_error" && stepErr.code !== "duplicate_phone" && <Alert>{stepErr.message}</Alert>}
          <div className="flex gap-2">
            <Button type="button" loading={busy} onClick={() => void submitNew()}>Создать клиента и авто</Button>
            <Button type="button" variant="secondary" onClick={reset}>Отмена</Button>
          </div>
        </div>
      )}

      {client && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2 rounded border border-border px-3 py-2 text-sm">
            <span className="min-w-0 truncate">
              <span className="font-medium">{client.full_name}</span> <span className="text-muted">{maskPhone(client.phone)}</span>
            </span>
            <Button type="button" variant="ghost" onClick={() => { onClient(null); onVehicle(""); reset(); }}>Сменить</Button>
          </div>
          {detail.isError && <Alert>{toAppError(detail.error).message}</Alert>}
          {vehicles.length > 0 && mode !== "newVehicle" && (
            <Select
              id="apt-vehicle"
              label="Автомобиль"
              value={vehicleId}
              onChange={(e) => (e.target.value === "__new" ? setMode("newVehicle") : onVehicle(e.target.value))}
              error={vehicleError}
            >
              <option value="">Выберите автомобиль</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>{[v.make, v.model, v.plate_number].filter(Boolean).join(" · ")}</option>
              ))}
              <option value="__new">+ Новое авто</option>
            </Select>
          )}
          {showVehicleForm && (
            <div className="space-y-3 rounded border border-border p-3">
              <div className="text-sm font-medium">Новый автомобиль</div>
              {vehicleFields}
              {stepErr && stepErr.code !== "validation_error" && <Alert>{stepErr.message}</Alert>}
              {vehicleError && vehicles.length === 0 && <Alert>{vehicleError}</Alert>}
              <div className="flex gap-2">
                <Button type="button" loading={busy} onClick={() => void submitVehicleOnly()}>Добавить авто</Button>
                {vehicles.length > 0 && <Button type="button" variant="secondary" onClick={reset}>Отмена</Button>}
              </div>
            </div>
          )}
        </div>
      )}
    </fieldset>
  );
}
