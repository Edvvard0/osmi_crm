import { type FormEvent, useMemo, useState } from "react";

import { useAllServices } from "@/features/catalog/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { type Appointment, type CrmLocation, DEPARTMENT_LABELS, type Department, type Post } from "@/shared/api/types";
import { Modal } from "@/shared/ui/modal";
import { Alert, Button, Input, Loading, Select, Textarea } from "@/shared/ui/ui";

import { type AppointmentCreate, type AppointmentPatch, useCreateAppointment, useUpdateAppointment } from "./api";
import { ClientVehiclePicker, type PickedClient } from "./ClientVehiclePicker";
import { TIME_ERROR_TEXT, defaultDurationMinutes, validateInterval } from "./grid";
import { dateOfMs, hhmm, isDateStr, minuteOfDay, parseHm, safeZone, toZonedIso, zonedTimeToMs } from "./time";

export interface FormInitial {
  postId: string | null;
  date: string;
  startMin: number;
  department?: Department;
}

interface Props {
  location: CrmLocation;
  /** Активные посты точки. */
  posts: Post[];
  appointment?: Appointment;
  initial?: FormInitial;
  onClose: () => void;
  onSaved: (a: Appointment) => void;
}

const COMMENT_MAX = 1000;
const DEPARTMENTS: Department[] = ["service", "detailing"];

/** Текст конфликта поста: время занятого интервала берётся из ответа сервера как дата, а не как текст. */
function conflictText(err: AppError, tz: string): string | null {
  const s = Date.parse(err.details.start_at ?? "");
  const e = Date.parse(err.details.end_at ?? "");
  if (Number.isNaN(s) || Number.isNaN(e)) return null;
  return `Занято с ${hhmm(minuteOfDay(s, tz))} до ${hhmm(minuteOfDay(e, tz))}`;
}

export function AppointmentForm({ location, posts, appointment, initial, onClose, onSaved }: Props) {
  const tz = safeZone(location.timezone);
  const edit = !!appointment;
  const create = useCreateAppointment();
  const update = useUpdateAppointment(appointment?.id ?? "");
  const m = edit ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  const work = useMemo(
    () => ({ start: parseHm(location.work_start) ?? 0, end: parseHm(location.work_end) ?? 24 * 60 }),
    [location.work_start, location.work_end],
  );

  const startMs = appointment ? Date.parse(appointment.start_at) : null;
  const endMs = appointment ? Date.parse(appointment.end_at) : null;

  const [client, setClient] = useState<PickedClient | null>(null);
  const [vehicleId, setVehicleId] = useState("");
  const [department, setDepartment] = useState<Department>(
    appointment?.department ?? initial?.department ?? posts.find((p) => p.id === initial?.postId)?.department ?? "service",
  );
  const [postId, setPostId] = useState(appointment ? (appointment.post_id ?? "") : (initial?.postId ?? ""));
  const [date, setDate] = useState(startMs !== null ? dateOfMs(startMs, tz) : (initial?.date ?? ""));
  const [start, setStart] = useState(startMs !== null ? hhmm(minuteOfDay(startMs, tz)) : hhmm(initial?.startMin ?? work.start));
  const [endManual, setEndManual] = useState<string | null>(endMs !== null ? hhmm(minuteOfDay(endMs, tz)) : null);
  const [serviceIds, setServiceIds] = useState<string[]>(appointment?.service_ids ?? []);
  const [comment, setComment] = useState(appointment?.comment ?? "");
  const [localErr, setLocalErr] = useState<Record<string, string>>({});

  const servicesQ = useAllServices({ is_active: true, location_id: location.id });
  const deptServices = (servicesQ.data ?? []).filter((s) => s.department === department);
  const chosen = deptServices.filter((s) => serviceIds.includes(s.id));

  const startMin = parseHm(start);
  const computedEnd = startMin === null ? "" : hhmm(Math.min(startMin + defaultDurationMinutes(chosen), 24 * 60 - 5));
  const end = endManual ?? computedEnd;

  const deptPosts = posts.filter((p) => p.department === department);

  function changeStart(v: string) {
    const prev = parseHm(start);
    const next = parseHm(v);
    const e = endManual === null ? null : parseHm(endManual);
    // Сдвиг начала сохраняет длительность.
    if (prev !== null && next !== null && e !== null) setEndManual(hhmm(Math.min(Math.max(e + (next - prev), 0), 24 * 60 - 5)));
    setStart(v);
  }

  function changeDepartment(d: Department) {
    setDepartment(d);
    if (!posts.some((p) => p.id === postId && p.department === d)) setPostId("");
    const ids = new Set((servicesQ.data ?? []).filter((s) => s.department === d).map((s) => s.id));
    setServiceIds((cur) => cur.filter((id) => ids.has(id)));
  }

  function toggleService(id: string) {
    setServiceIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    if (!edit) {
      if (!client) le.client_id = "Выберите клиента";
      else if (!vehicleId) le.vehicle_id = "Выберите автомобиль";
    }
    const s = parseHm(start);
    const en = parseHm(end);
    if (!isDateStr(date)) le.date = "Укажите дату";
    if (s === null) le.start = "Укажите время начала";
    if (en === null) le.end = "Укажите время окончания";
    if (s !== null && en !== null) {
      const te = validateInterval({ start: s, end: en }, work);
      if (te) le.end = TIME_ERROR_TEXT[te];
    }
    if (comment.length > COMMENT_MAX) le.comment = "Не больше 1000 символов";
    setLocalErr(le);
    if (Object.keys(le).length || s === null || en === null) return;

    const startIso = toZonedIso(zonedTimeToMs(date, s, tz), tz);
    const endIso = toZonedIso(zonedTimeToMs(date, en, tz), tz);
    const post = postId || null;
    const c = comment.trim() || null;

    if (appointment) {
      const patch: AppointmentPatch = {};
      if (post !== appointment.post_id) patch.post_id = post;
      if (department !== appointment.department) patch.department = department;
      if (Date.parse(startIso) !== Date.parse(appointment.start_at) || Date.parse(endIso) !== Date.parse(appointment.end_at)) {
        patch.start_at = startIso;
        patch.end_at = endIso;
      }
      const same = serviceIds.length === appointment.service_ids.length && serviceIds.every((id) => appointment.service_ids.includes(id));
      if (!same) patch.service_ids = serviceIds;
      if (c !== (appointment.comment ?? null)) patch.comment = c;
      if (Object.keys(patch).length === 0) {
        onClose();
        return;
      }
      update.mutate(patch, { onSuccess: onSaved });
      return;
    }
    if (!client) return;
    const body: AppointmentCreate = {
      location_id: location.id,
      client_id: client.id,
      vehicle_id: vehicleId,
      department,
      start_at: startIso,
      end_at: endIso,
      ...(post ? { post_id: post } : {}),
      ...(serviceIds.length ? { service_ids: serviceIds } : {}),
      ...(c ? { comment: c } : {}),
    };
    create.mutate(body, { onSuccess: onSaved });
  }

  const busy = err?.code === "post_busy";
  const srv = (n: string) => (err?.code === "validation_error" ? fieldMessage(err, n) : undefined);
  const showAlert = err && err.code !== "validation_error";

  return (
    <Modal title={edit ? "Редактирование записи" : "Новая запись"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {edit && appointment ? (
          <div className="rounded border border-border px-3 py-2 text-sm">
            <span className="font-medium">{appointment.client.full_name}</span>{" "}
            <span className="text-muted">
              {appointment.vehicle.plate_number || `${appointment.vehicle.make} ${appointment.vehicle.model}`}
            </span>
          </div>
        ) : (
          <ClientVehiclePicker
            client={client}
            onClient={setClient}
            vehicleId={vehicleId}
            onVehicle={setVehicleId}
            clientError={localErr.client_id ?? srv("client_id")}
            vehicleError={localErr.vehicle_id ?? srv("vehicle_id")}
          />
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Select id="apt-department" label="Отдел" value={department} onChange={(e) => changeDepartment(e.target.value as Department)} error={srv("department")}>
            {DEPARTMENTS.map((d) => (
              <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
            ))}
          </Select>
          <Select id="apt-post" label="Пост" value={postId} onChange={(e) => setPostId(e.target.value)} error={srv("post_id")}>
            <option value="">Без поста</option>
            {deptPosts.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <Input id="apt-date" label="Дата" type="date" value={date} onChange={(e) => setDate(e.target.value)} error={localErr.date} />
          <Input id="apt-start" label="Начало" type="time" step={300} value={start} onChange={(e) => changeStart(e.target.value)} error={localErr.start ?? srv("start_at")} />
          <Input id="apt-end" label="Окончание" type="time" step={300} value={end} onChange={(e) => setEndManual(e.target.value)} error={localErr.end ?? srv("end_at")} />
        </div>
        <p className="-mt-2 text-xs text-muted">
          Рабочие часы точки: {location.work_start.slice(0, 5)}–{location.work_end.slice(0, 5)}. Время указывается по часовому поясу точки.
        </p>

        <fieldset className="space-y-1">
          <legend className="mb-1 text-sm font-medium">Услуги</legend>
          {servicesQ.isLoading && <Loading />}
          {servicesQ.isError && <Alert>{toAppError(servicesQ.error).message}</Alert>}
          {servicesQ.isSuccess && deptServices.length === 0 && <p className="text-sm text-muted">В этом отделе нет активных услуг</p>}
          <div className="max-h-48 divide-y divide-border overflow-auto rounded border border-border empty:hidden">
            {deptServices.map((s) => (
              <label key={s.id} className="flex min-h-10 cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-border/30">
                <input type="checkbox" className="h-4 w-4" checked={serviceIds.includes(s.id)} onChange={() => toggleService(s.id)} />
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                <span className="shrink-0 text-xs text-muted">{s.duration_minutes} мин</span>
              </label>
            ))}
          </div>
          {srv("service_ids") && <p role="alert" className="text-xs text-danger">{srv("service_ids")}</p>}
        </fieldset>

        <Textarea id="apt-comment" label="Комментарий" value={comment} onChange={(e) => setComment(e.target.value)} error={localErr.comment ?? srv("comment")} />

        {showAlert && (
          <Alert>
            {err.message}
            {busy && conflictText(err, tz) ? `. ${conflictText(err, tz)}` : ""}
          </Alert>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={m.isPending}>{edit ? "Сохранить" : "Создать запись"}</Button>
        </div>
      </form>
    </Modal>
  );
}
