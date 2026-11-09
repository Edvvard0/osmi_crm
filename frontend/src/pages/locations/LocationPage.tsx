import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useCreateLocation, useLocationById, useUpdateLocation } from "@/features/locations/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import type { CrmLocation } from "@/shared/api/types";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Input, LinkButton, Loading } from "@/shared/ui/ui";

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
  const toast = useToast();
  const create = useCreateLocation();
  const update = useUpdateLocation(loc?.id ?? "");
  const toggle = useUpdateLocation(loc?.id ?? "", false);
  const [name, setName] = useState(loc?.name ?? "");
  const [address, setAddress] = useState(loc?.address ?? "");
  const [phone, setPhone] = useState(loc?.phone ?? "");
  const [localErr, setLocalErr] = useState<Record<string, string>>({});

  const m = loc ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;
  const nameErr = localErr.name ?? fieldMessage(err, "name");
  const addrErr = localErr.address ?? fieldMessage(err, "address");
  const phoneErr = fieldMessage(err, "phone");
  const showAlert = err && err.code !== "validation_error";

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    if (!name.trim()) le.name = "Обязательное поле";
    if (!address.trim()) le.address = "Обязательное поле";
    setLocalErr(le);
    if (Object.keys(le).length) return;
    const p = phone.trim();
    if (loc) {
      update.mutate({ name: name.trim(), address: address.trim(), phone: p || null }, { onSuccess: () => toast.push("success", "Сохранено") });
    } else {
      create.mutate({ name: name.trim(), address: address.trim(), ...(p ? { phone: p } : {}) }, { onSuccess: (l) => nav(`/locations/${l.id}`, { replace: true }) });
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
        {showAlert && <Alert>{err.message}</Alert>}
        <Button type="submit" loading={m.isPending}>{loc ? "Сохранить" : "Создать"}</Button>
      </form>
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
