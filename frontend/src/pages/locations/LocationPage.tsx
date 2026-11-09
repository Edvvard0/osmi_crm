import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { LocationTelegram } from "@/features/telegram/LocationTelegram";
import { useCreateLocation, useLocationById, useUpdateLocation } from "@/features/locations/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import type { CrmLocation } from "@/shared/api/types";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Input, LinkButton, Loading, Select } from "@/shared/ui/ui";

const DEFAULT_TZ = "Europe/Moscow";
const DEFAULT_START = "09:00";
const DEFAULT_END = "21:00";

/** Часовые пояса России и ближнего зарубежья; текущее значение точки добавляется, если его нет в списке. */
const TIMEZONES: [string, string][] = [
  ["Europe/Kaliningrad", "Калининград (UTC+2)"],
  ["Europe/Moscow", "Москва (UTC+3)"],
  ["Europe/Samara", "Самара (UTC+4)"],
  ["Asia/Yekaterinburg", "Екатеринбург (UTC+5)"],
  ["Asia/Omsk", "Омск (UTC+6)"],
  ["Asia/Novosibirsk", "Новосибирск (UTC+7)"],
  ["Asia/Krasnoyarsk", "Красноярск (UTC+7)"],
  ["Asia/Irkutsk", "Иркутск (UTC+8)"],
  ["Asia/Yakutsk", "Якутск (UTC+9)"],
  ["Asia/Vladivostok", "Владивосток (UTC+10)"],
  ["Asia/Magadan", "Магадан (UTC+11)"],
  ["Asia/Kamchatka", "Камчатка (UTC+12)"],
  ["Europe/Minsk", "Минск (UTC+3)"],
  ["Asia/Almaty", "Алматы (UTC+5)"],
  ["UTC", "UTC"],
];

const hm = (v: string | undefined, fallback: string) => (v ? v.slice(0, 5) : fallback);

/** Карточка точки и форма создания (/locations/new) */
export function LocationPage() {
  const { id } = useParams();
  const q = useLocationById(id);
  if (id === "new") return <LocationForm />;
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert>{toAppError(q.error).message}</Alert>;
  return <LocationForm loc={q.data} />;
}

function LocationForm({ loc }: { loc?: CrmLocation }) {
  const nav = useNavigate();
  const me = useMe();
  const toast = useToast();
  const create = useCreateLocation();
  const update = useUpdateLocation(loc?.id ?? "");
  const toggle = useUpdateLocation(loc?.id ?? "", false);
  const [name, setName] = useState(loc?.name ?? "");
  const [address, setAddress] = useState(loc?.address ?? "");
  const [phone, setPhone] = useState(loc?.phone ?? "");
  const [tz, setTz] = useState(loc?.timezone ?? DEFAULT_TZ);
  const [workStart, setWorkStart] = useState(hm(loc?.work_start, DEFAULT_START));
  const [workEnd, setWorkEnd] = useState(hm(loc?.work_end, DEFAULT_END));
  const [localErr, setLocalErr] = useState<Record<string, string>>({});

  const m = loc ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;
  const nameErr = localErr.name ?? fieldMessage(err, "name");
  const addrErr = localErr.address ?? fieldMessage(err, "address");
  const phoneErr = fieldMessage(err, "phone");
  const tzErr = fieldMessage(err, "timezone");
  const startErr = localErr.work_start ?? fieldMessage(err, "work_start");
  const endErr = localErr.work_end ?? fieldMessage(err, "work_end");
  const tzOptions = TIMEZONES.some(([v]) => v === tz) ? TIMEZONES : [[tz, tz] as [string, string], ...TIMEZONES];
  const showAlert = err && err.code !== "validation_error";

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    if (!name.trim()) le.name = "Обязательное поле";
    if (!address.trim()) le.address = "Обязательное поле";
    if (!/^\d{2}:\d{2}$/.test(workStart)) le.work_start = "Укажите время";
    if (!/^\d{2}:\d{2}$/.test(workEnd)) le.work_end = "Укажите время";
    if (!le.work_start && !le.work_end && workEnd <= workStart) le.work_end = "Окончание работы должно быть позже начала";
    setLocalErr(le);
    if (Object.keys(le).length) return;
    const p = phone.trim();
    if (loc) {
      // Расписание отправляется только если изменилось: лишние поля не нужны серверу.
      const sched: Record<string, string> = {};
      if (tz !== loc.timezone) sched.timezone = tz;
      if (workStart !== hm(loc.work_start, workStart)) sched.work_start = workStart;
      if (workEnd !== hm(loc.work_end, workEnd)) sched.work_end = workEnd;
      update.mutate({ name: name.trim(), address: address.trim(), phone: p || null, ...sched }, { onSuccess: () => toast.push("success", "Сохранено") });
    } else {
      const sched: Record<string, string> = {};
      if (tz !== DEFAULT_TZ) sched.timezone = tz;
      if (workStart !== DEFAULT_START) sched.work_start = workStart;
      if (workEnd !== DEFAULT_END) sched.work_end = workEnd;
      create.mutate({ name: name.trim(), address: address.trim(), ...(p ? { phone: p } : {}), ...sched }, { onSuccess: (l) => nav(`/locations/${l.id}`, { replace: true }) });
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{loc ? loc.name : "Новая точка"}</h1>
          {loc && <div className="mt-1"><Badge tone={loc.is_active ? "success" : "neutral"}>{loc.is_active ? "Работает" : "Закрыта"}</Badge></div>}
        </div>
        <LinkButton to="/locations" variant="secondary">К списку</LinkButton>
      </div>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Input label="Название" value={name} onChange={(e) => setName(e.target.value)} error={nameErr} />
        <Input label="Адрес" value={address} onChange={(e) => setAddress(e.target.value)} error={addrErr} />
        <Input label="Телефон" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} error={phoneErr} />
        <Select label="Часовой пояс" id="loc-tz" value={tz} onChange={(e) => setTz(e.target.value)} error={tzErr}>
          {tzOptions.map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </Select>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Начало работы" id="loc-work-start" type="time" value={workStart} onChange={(e) => setWorkStart(e.target.value)} error={startErr} />
          <Input label="Конец работы" id="loc-work-end" type="time" value={workEnd} onChange={(e) => setWorkEnd(e.target.value)} error={endErr} />
        </div>
        {showAlert && <Alert>{err.message}</Alert>}
        <Button type="submit" loading={m.isPending}>{loc ? "Сохранить" : "Создать"}</Button>
      </form>
      {loc && <LocationTelegram loc={loc} isDirector={me.role === "director"} />}
      {loc && (
        <section className="border-t border-border pt-4">
          <Button
            variant={loc.is_active ? "danger" : "secondary"}
            loading={toggle.isPending}
            onClick={() => toggle.mutate({ is_active: !loc.is_active })}
          >
            {loc.is_active ? "Закрыть точку" : "Открыть точку"}
          </Button>
          <p className="mt-2 text-xs text-muted">Точки не удаляются: закрытая точка скрывается из рабочих списков.</p>
        </section>
      )}
    </div>
  );
}
