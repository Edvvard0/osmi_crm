import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { type ClientInput, useClientById, useCreateClient, useUpdateClient } from "@/features/clients/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { type Client, type ClientSource, type ClientType, SOURCE_LABELS } from "@/shared/api/types";
import { isValidEmail, isValidInn, maskPhone, normalizePhone } from "@/shared/lib/masks";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Input, LinkButton, Loading, Select, Textarea } from "@/shared/ui/ui";

/** MG-09: форма клиента (/clients/new и /clients/:id/edit). Страница — на весь экран и на мобильном. */
export function ClientFormPage() {
  const { id } = useParams();
  const q = useClientById(id);
  if (!id) return <ClientForm />;
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert>{toAppError(q.error).message}</Alert>;
  return <ClientForm client={q.data} />;
}

/** Дубль телефона: сообщение из словаря и ссылка на существующего клиента (имя — только как текст). */
export function DuplicateNotice({ err }: { err: AppError }) {
  if (err.code !== "duplicate_phone") return null;
  const eid = err.details.existing_id;
  return (
    <div role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
      {err.message}
      {eid && (
        <>
          {": "}
          <Link className="font-medium underline" to={`/clients/${encodeURIComponent(eid)}`}>
            {err.details.existing_name || "открыть клиента"}
          </Link>
        </>
      )}
    </div>
  );
}

const PHONE_HINT = "Введите номер полностью: +7 (999) 123-45-67";

function ClientForm({ client }: { client?: Client }) {
  const nav = useNavigate();
  const toast = useToast();
  const create = useCreateClient();
  const update = useUpdateClient(client?.id ?? "");
  const m = client ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  const [type, setType] = useState<ClientType>(client?.client_type ?? "person");
  const [fullName, setFullName] = useState(client?.full_name ?? "");
  const [company, setCompany] = useState(client?.company_name ?? "");
  const [inn, setInn] = useState(client?.inn ?? "");
  const [phone, setPhone] = useState(client ? maskPhone(client.phone) : "");
  const [phone2, setPhone2] = useState(client?.phone_extra ? maskPhone(client.phone_extra) : "");
  const [email, setEmail] = useState(client?.email ?? "");
  const [source, setSource] = useState<"" | ClientSource>(client?.source ?? "");
  const [discount, setDiscount] = useState(String(client?.discount_percent ?? 0));
  const [notes, setNotes] = useState(client?.notes ?? "");
  const [localErr, setLocalErr] = useState<Record<string, string>>({});

  const srv = (name: string) => (err?.code === "validation_error" ? fieldMessage(err, name) : undefined);
  const showAlert = err && err.code !== "validation_error" && err.code !== "duplicate_phone";

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    const p1 = normalizePhone(phone);
    const p2 = phone2 ? normalizePhone(phone2) : null;
    const d = Number(discount.replace(",", "."));
    if (!fullName.trim()) le.full_name = "Обязательное поле";
    if (type === "company" && !company.trim()) le.company_name = "Обязательное поле";
    if (!p1) le.phone = phone ? PHONE_HINT : "Обязательное поле";
    if (phone2 && !p2) le.phone_extra = PHONE_HINT;
    if (inn.trim() && !isValidInn(inn.trim())) le.inn = "ИНН: 10 или 12 цифр";
    if (email.trim() && !isValidEmail(email.trim())) le.email = "Некорректный email";
    if (discount.trim() === "" || !Number.isFinite(d) || d < 0 || d > 100) le.discount_percent = "Скидка: число от 0 до 100";
    setLocalErr(le);
    if (Object.keys(le).length || !p1) return;

    const body: ClientInput = {
      client_type: type,
      full_name: fullName.trim(),
      company_name: type === "company" ? company.trim() : null,
      inn: type === "company" && inn.trim() ? inn.trim() : null,
      phone: p1,
      phone_extra: p2,
      email: email.trim() || null,
      source: source || null,
      discount_percent: d,
      notes: notes.trim() || null,
    };
    if (client) {
      update.mutate(body, {
        onSuccess: () => {
          toast.push("success", "Сохранено");
          nav(`/clients/${encodeURIComponent(client.id)}`);
        },
      });
    } else {
      create.mutate(body, { onSuccess: (c) => nav(`/clients/${encodeURIComponent(c.id)}`, { replace: true }) });
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{client ? "Редактирование клиента" : "Новый клиент"}</h1>
        <LinkButton to={client ? `/clients/${encodeURIComponent(client.id)}` : "/clients"} variant="secondary">Отмена</LinkButton>
      </div>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Select label="Тип клиента" value={type} onChange={(e) => setType(e.target.value as ClientType)}>
          <option value="person">Физлицо</option>
          <option value="company">Компания</option>
        </Select>
        <Input label={type === "company" ? "Контактное лицо" : "ФИО"} value={fullName} onChange={(e) => setFullName(e.target.value)} error={localErr.full_name ?? srv("full_name")} />
        {type === "company" && (
          <>
            <Input label="Название компании" value={company} onChange={(e) => setCompany(e.target.value)} error={localErr.company_name ?? srv("company_name")} />
            <Input label="ИНН" inputMode="numeric" maxLength={12} value={inn} onChange={(e) => setInn(e.target.value.replace(/\D/g, ""))} error={localErr.inn ?? srv("inn")} />
          </>
        )}
        <Input label="Телефон" type="tel" inputMode="tel" autoComplete="off" placeholder="+7 (999) 123-45-67" value={phone} onChange={(e) => setPhone(maskPhone(e.target.value))} error={localErr.phone ?? srv("phone")} />
        <Input label="Доп. телефон" type="tel" inputMode="tel" autoComplete="off" placeholder="+7 (999) 123-45-67" value={phone2} onChange={(e) => setPhone2(maskPhone(e.target.value))} error={localErr.phone_extra ?? srv("phone_extra")} />
        <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={localErr.email ?? srv("email")} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="Источник" value={source} onChange={(e) => setSource(e.target.value as "" | ClientSource)}>
            <option value="">Не указан</option>
            {(Object.keys(SOURCE_LABELS) as ClientSource[]).map((s) => (
              <option key={s} value={s}>{SOURCE_LABELS[s]}</option>
            ))}
          </Select>
          <Input label="Скидка, %" inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} error={localErr.discount_percent ?? srv("discount_percent")} />
        </div>
        <Textarea label="Заметки" value={notes} onChange={(e) => setNotes(e.target.value)} error={srv("notes")} />
        {err && <DuplicateNotice err={err} />}
        {showAlert && <Alert>{err.message}</Alert>}
        <Button type="submit" loading={m.isPending} className="w-full sm:w-auto">{client ? "Сохранить" : "Создать"}</Button>
      </form>
    </div>
  );
}
