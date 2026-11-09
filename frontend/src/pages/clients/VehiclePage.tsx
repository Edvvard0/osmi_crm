import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useArchiveVehicle, useVehicleById } from "@/features/clients/api";
import { toAppError } from "@/shared/api/errors";
import type { VehicleDetail } from "@/shared/api/types";
import { Alert, Badge, Button, Dialog, LinkButton, Loading } from "@/shared/ui/ui";

import { Field } from "./ClientPage";

/** Карточка автомобиля: /vehicles/:id */
export function VehiclePage() {
  const { id } = useParams();
  const q = useVehicleById(id);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert>{toAppError(q.error).message}</Alert>;
  return <VehicleCard v={q.data} />;
}

function VehicleCard({ v }: { v: VehicleDetail }) {
  const nav = useNavigate();
  const archive = useArchiveVehicle(v.id);
  const [confirm, setConfirm] = useState(false);
  const archived = !!v.archived_at;
  const clientHref = `/clients/${encodeURIComponent(v.client.id)}`;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{v.make} {v.model}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span>{v.plate_number ?? "без госномера"}</span>
            {archived && <Badge tone="warning">В архиве</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton to={clientHref} variant="secondary">К клиенту</LinkButton>
          <LinkButton to={`/vehicles/${encodeURIComponent(v.id)}/edit`} variant="secondary">Изменить</LinkButton>
          {archived ? (
            <Button variant="secondary" loading={archive.isPending} onClick={() => archive.mutate(false)}>Восстановить</Button>
          ) : (
            <Button variant="secondary" onClick={() => setConfirm(true)}>Архивировать</Button>
          )}
        </div>
      </div>

      <dl className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2">
        <Field label="Владелец">
          <Link className="underline-offset-2 hover:underline" to={clientHref}>{v.client.full_name}</Link>
          <span className="block text-xs text-muted">{v.client.phone}</span>
        </Field>
        <Field label="Госномер">{v.plate_number}</Field>
        <Field label="VIN">{v.vin}</Field>
        <Field label="Год выпуска">{v.year}</Field>
        <Field label="Цвет">{v.color}</Field>
        <Field label="Пробег">{v.mileage !== null ? `${v.mileage.toLocaleString("ru-RU")} км` : null}</Field>
      </dl>

      <section aria-labelledby="v-notes" className="space-y-2">
        <h2 id="v-notes" className="text-base font-semibold">Заметки</h2>
        <p className="whitespace-pre-wrap break-words rounded-lg border border-border bg-surface p-4 text-sm">{v.notes || "—"}</p>
      </section>

      <Dialog open={confirm} title="Архивировать автомобиль?" onClose={() => setConfirm(false)}>
        <p className="text-sm text-muted">Автомобиль исчезнет из списка клиента. Его можно будет восстановить.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(false)}>Отмена</Button>
          <Button
            loading={archive.isPending}
            onClick={() => archive.mutate(true, { onSuccess: () => { setConfirm(false); nav(clientHref); } })}
          >
            Архивировать
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
