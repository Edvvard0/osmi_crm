import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useArchiveClient, useClientById } from "@/features/clients/api";
import { toAppError } from "@/shared/api/errors";
import { type ClientDetail, SOURCE_LABELS } from "@/shared/api/types";
import { Alert, Badge, Button, Dialog, LinkButton, Loading } from "@/shared/ui/ui";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{children || "—"}</dd>
    </div>
  );
}

/** MG-09 «Карточка клиента» */
export function ClientPage() {
  const { id } = useParams();
  const q = useClientById(id);
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert>{toAppError(q.error).message}</Alert>;
  return <ClientCard c={q.data} />;
}

function ClientCard({ c }: { c: ClientDetail }) {
  const archive = useArchiveClient(c.id);
  const [confirm, setConfirm] = useState(false);
  const archived = !!c.archived_at;
  const cid = encodeURIComponent(c.id);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{c.full_name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <span>{c.client_type === "company" ? "Компания" : "Физлицо"}</span>
            {archived && <Badge tone="warning">В архиве</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <LinkButton to="/clients" variant="secondary">К списку</LinkButton>
          <LinkButton to={`/clients/${cid}/edit`} variant="secondary">Изменить</LinkButton>
          {archived ? (
            <Button variant="secondary" loading={archive.isPending} onClick={() => archive.mutate(false)}>Восстановить</Button>
          ) : (
            <Button variant="secondary" onClick={() => setConfirm(true)}>Архивировать</Button>
          )}
        </div>
      </div>

      <section aria-labelledby="c-contacts" className="space-y-3">
        <h2 id="c-contacts" className="text-base font-semibold">Контакты</h2>
        <dl className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2">
          {c.company_name && <Field label="Компания">{c.company_name}</Field>}
          {c.inn && <Field label="ИНН">{c.inn}</Field>}
          <Field label="Телефон">{c.phone}</Field>
          <Field label="Доп. телефон">{c.phone_extra}</Field>
          <Field label="Email">{c.email}</Field>
          <Field label="Источник">{c.source ? SOURCE_LABELS[c.source] : null}</Field>
          <Field label="Скидка">{c.discount_percent}%</Field>
        </dl>
      </section>

      <section aria-labelledby="c-notes" className="space-y-2">
        <h2 id="c-notes" className="text-base font-semibold">Заметки</h2>
        <p className="whitespace-pre-wrap break-words rounded-lg border border-border bg-surface p-4 text-sm">{c.notes || "—"}</p>
      </section>

      <section aria-labelledby="c-cars" className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 id="c-cars" className="text-base font-semibold">Автомобили</h2>
          {!archived && <LinkButton to={`/clients/${cid}/vehicles/new`}>+ Добавить авто</LinkButton>}
        </div>
        {c.vehicles.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface p-4 text-sm text-muted">Автомобилей пока нет</p>
        ) : (
          <ul className="space-y-2">
            {c.vehicles.map((v) => (
              <li key={v.id} className="rounded-lg border border-border bg-surface p-3">
                <Link to={`/vehicles/${encodeURIComponent(v.id)}`} className="font-medium underline-offset-2 hover:underline">
                  {v.make} {v.model}
                </Link>
                <div className="mt-1 text-sm text-muted">
                  {[v.plate_number, v.year, v.vin].filter(Boolean).join(" · ") || "—"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="c-orders" className="space-y-2">
        <h2 id="c-orders" className="text-base font-semibold">История заказов</h2>
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">История заказов появится позже</p>
      </section>

      <Dialog open={confirm} title="Архивировать клиента?" onClose={() => setConfirm(false)}>
        <p className="text-sm text-muted">Клиент исчезнет из списка активных. Его можно будет восстановить.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirm(false)}>Отмена</Button>
          <Button loading={archive.isPending} onClick={() => archive.mutate(true, { onSuccess: () => setConfirm(false) })}>Архивировать</Button>
        </div>
      </Dialog>
    </div>
  );
}
