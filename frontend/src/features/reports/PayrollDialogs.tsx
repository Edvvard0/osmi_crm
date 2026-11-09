import { type FormEvent, useMemo, useState } from "react";

import { useUsers } from "@/features/users/api";
import { toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS, type Department } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Input, Select, Textarea } from "@/shared/ui/ui";

import { type SchemeInput, useCreateAdjustment, useCreateScheme, useDeleteScheme, useEndScheme, usePayrollSchemes } from "./api";
import { EmptyNote } from "./filters";
import { firstOfMonth, formatDate, isMonth, parseSigned, reportFieldText, useToday } from "./lib";
import type { PayrollScheme, PayrollSchemeType, UserRef } from "./types";

/** Сотрудники для выбора: первые 50 активных + выбранный заранее. */
function useEmployeeOptions(initial: UserRef | null): UserRef[] {
  const q = useUsers({ search: "", role: "", location_id: "", is_active: "true", offset: 0 });
  return useMemo(() => {
    const list: UserRef[] = (q.data?.items ?? []).map((u) => ({ id: u.id, full_name: u.full_name }));
    if (initial && !list.some((u) => u.id === initial.id)) list.unshift(initial);
    return list;
  }, [q.data, initial]);
}

/* ---------- Премия / удержание ---------- */

export function AdjustmentDialog({ month, user, onClose }: { month: string; user: UserRef | null; onClose: () => void }) {
  const toast = useToast();
  const today = useToday();
  const currentMonth = today.slice(0, 7);
  const employees = useEmployeeOptions(user);
  const create = useCreateAdjustment();
  const [userId, setUserId] = useState(user?.id ?? "");
  const [m, setM] = useState(month);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [local, setLocal] = useState<Record<string, string>>({});

  const err = create.error ? toAppError(create.error) : null;
  const fe = (n: string) => local[n] ?? reportFieldText(err, n);
  const generic = err && err.code !== "validation_error" ? err.message : null;
  const selected = userId || employees[0]?.id || "";

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    const signed = parseSigned(amount);
    if (!selected) le.user_id = "Выберите сотрудника";
    if (!isMonth(m) || m > currentMonth) le.month = "Месяц: не в будущем";
    if (signed === null) le.amount = "Сумма: число, не равное нулю, до двух знаков после запятой";
    const r = reason.trim();
    if (r.length < 1 || r.length > 500) le.reason = "Причина: от 1 до 500 символов";
    setLocal(le);
    if (Object.keys(le).length || signed === null) return;
    create.mutate(
      { user_id: selected, month: m, amount: signed, reason: r },
      {
        onSuccess: () => {
          toast.push("success", "Корректировка сохранена");
          onClose();
        },
      },
    );
  }

  return (
    <Modal title="Премия / удержание" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Select label="Сотрудник" value={selected} onChange={(e) => setUserId(e.target.value)} error={fe("user_id")}>
          {employees.map((u) => (
            <option key={u.id} value={u.id}>{u.full_name}</option>
          ))}
        </Select>
        <Input label="Месяц" type="month" value={m} max={currentMonth} onChange={(e) => setM(e.target.value)} error={fe("month")} />
        <Input
          label="Сумма, ₽"
          inputMode="decimal"
          autoComplete="off"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          error={fe("amount")}
        />
        <p className="-mt-1 text-xs text-muted">Премия — положительное число, удержание — со знаком минус. Исправить запись можно только новой, с обратным знаком.</p>
        <Textarea label="Причина" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} error={fe("reason")} />
        {generic && <Alert>{generic}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={create.isPending}>Сохранить</Button>
        </div>
      </form>
    </Modal>
  );
}

/* ---------- Схемы оплаты ---------- */

const SCHEME_TYPES: { value: PayrollSchemeType; label: string }[] = [
  { value: "percent_of_works", label: "Процент от работ" },
  { value: "per_norm_hour", label: "Ставка за нормочас" },
  { value: "fixed_plus_percent", label: "Оклад + процент" },
  { value: "fixed", label: "Оклад" },
];

function schemeStatus(s: PayrollScheme, today: string): { label: string; tone: "success" | "warning" | "neutral" } {
  if (s.valid_from > today) return { label: "Запланирована", tone: "warning" };
  if (s.valid_to !== null && s.valid_to < today) return { label: "Завершена", tone: "neutral" };
  return { label: "Действует", tone: "success" };
}

function SchemeRow({ s, today }: { s: PayrollScheme; today: string }) {
  const end = useEndScheme();
  const del = useDeleteScheme();
  const [ending, setEnding] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const minEnd = s.valid_from > firstOfMonth(today) ? s.valid_from : firstOfMonth(today);
  const [validTo, setValidTo] = useState(minEnd > today ? minEnd : today);
  const st = schemeStatus(s, today);
  const future = s.valid_from > today;
  const canEnd = s.valid_to === null || s.valid_to >= firstOfMonth(today);

  const endErr = end.error ? toAppError(end.error) : null;
  const delErr = del.error ? toAppError(del.error) : null;
  const err = endErr ?? delErr;
  const text = err ? (reportFieldText(err, "valid_to") ?? err.message) : null;

  return (
    <li className="space-y-2 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="break-words font-medium">{s.description}</p>
          <p className="text-xs text-muted">
            {s.department ? DEPARTMENT_LABELS[s.department as Department] : "Все отделы"} · с {formatDate(s.valid_from)}
            {s.valid_to ? ` по ${formatDate(s.valid_to)}` : ", без срока"}
          </p>
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      {!ending && !confirmDel && (
        <div className="flex flex-wrap gap-2">
          {canEnd && !future && <Button variant="secondary" onClick={() => setEnding(true)}>Завершить</Button>}
          {future && <Button variant="secondary" onClick={() => setConfirmDel(true)}>Удалить</Button>}
        </div>
      )}
      {ending && (
        <form
          className="flex flex-wrap items-end gap-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            end.mutate({ id: s.id, valid_to: validTo }, { onSuccess: () => setEnding(false) });
          }}
        >
          <div className="w-44">
            <Input label="Дата окончания" type="date" value={validTo} min={minEnd} onChange={(e) => setValidTo(e.target.value)} />
          </div>
          <Button type="submit" loading={end.isPending}>Сохранить дату</Button>
          <Button type="button" variant="secondary" onClick={() => { setEnding(false); end.reset(); }}>Отмена</Button>
        </form>
      )}
      {confirmDel && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">Удалить запланированную схему?</span>
          <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(s.id, { onSuccess: () => setConfirmDel(false) })}>Да, удалить</Button>
          <Button variant="secondary" onClick={() => { setConfirmDel(false); del.reset(); }}>Отмена</Button>
        </div>
      )}
      {text && <p role="alert" className="text-sm text-danger">{text}</p>}
    </li>
  );
}

function NewSchemeForm({ userId, today }: { userId: string; today: string }) {
  const create = useCreateScheme();
  const [type, setType] = useState<PayrollSchemeType>("percent_of_works");
  const [percent, setPercent] = useState("");
  const [rate, setRate] = useState("");
  const [fixed, setFixed] = useState("");
  const [dept, setDept] = useState<"" | Department>("");
  const [from, setFrom] = useState(today);
  const [local, setLocal] = useState<Record<string, string>>({});

  const needPercent = type === "percent_of_works" || type === "fixed_plus_percent";
  const needRate = type === "per_norm_hour";
  const needFixed = type === "fixed" || type === "fixed_plus_percent";
  const err = create.error ? toAppError(create.error) : null;
  const fe = (n: string) => local[n] ?? reportFieldText(err, n);
  const generic = err && err.code !== "validation_error" ? err.message : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    const body: SchemeInput = { user_id: userId, scheme_type: type, valid_from: from, department: needFixed ? null : dept || null };
    if (needPercent) {
      const p = parseDecimal(percent, 2);
      if (p === null || Number(p) > 100) le.percent = "Процент: число от 0 до 100, до двух знаков после запятой";
      else body.percent = p;
    }
    if (needRate) {
      const r = parseDecimal(rate, 2);
      if (r === null) le.norm_hour_rate = "Ставка за нормочас: число не меньше 0, до двух знаков после запятой";
      else body.norm_hour_rate = r;
    }
    if (needFixed) {
      const f = parseDecimal(fixed, 2);
      if (f === null) le.fixed_monthly = "Оклад: число не меньше 0, до двух знаков после запятой";
      else body.fixed_monthly = f;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from)) le.valid_from = "Укажите дату начала";
    setLocal(le);
    if (Object.keys(le).length) return;
    create.mutate(body, {
      onSuccess: () => {
        setPercent("");
        setRate("");
        setFixed("");
      },
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate aria-label="Новая схема">
      <h3 className="text-sm font-medium">Новая схема</h3>
      <Select label="Тип схемы" value={type} onChange={(e) => { setType(e.target.value as PayrollSchemeType); setLocal({}); create.reset(); }} error={fe("scheme_type")}>
        {SCHEME_TYPES.map((t) => (
          <option key={t.value} value={t.value}>{t.label}</option>
        ))}
      </Select>
      {needPercent && <Input label="Процент от работ, %" inputMode="decimal" autoComplete="off" value={percent} onChange={(e) => setPercent(e.target.value)} error={fe("percent")} />}
      {needRate && <Input label="Ставка за нормочас, ₽" inputMode="decimal" autoComplete="off" value={rate} onChange={(e) => setRate(e.target.value)} error={fe("norm_hour_rate")} />}
      {needFixed && <Input label="Оклад в месяц, ₽" inputMode="decimal" autoComplete="off" value={fixed} onChange={(e) => setFixed(e.target.value)} error={fe("fixed_monthly")} />}
      {!needFixed && (
        <Select label="Отдел" value={dept} onChange={(e) => setDept(e.target.value as "" | Department)} error={fe("department")}>
          <option value="">Все отделы</option>
          <option value="service">{DEPARTMENT_LABELS.service}</option>
          <option value="detailing">{DEPARTMENT_LABELS.detailing}</option>
        </Select>
      )}
      <Input label="Действует с" type="date" value={from} onChange={(e) => setFrom(e.target.value)} error={fe("valid_from")} />
      <p className="text-xs text-muted">
        Начало нельзя ставить раньше первого числа текущего месяца (для первой схемы сотрудника ограничения нет). Открытая схема этой области закроется накануне даты начала.
      </p>
      {generic && <Alert>{generic}</Alert>}
      <div className="flex justify-end">
        <Button type="submit" loading={create.isPending}>Добавить схему</Button>
      </div>
    </form>
  );
}

export function SchemesDialog({ user, onClose }: { user: UserRef | null; onClose: () => void }) {
  const today = useToday();
  const employees = useEmployeeOptions(user);
  const [userId, setUserId] = useState(user?.id ?? "");
  const selected = userId || employees[0]?.id || "";
  const q = usePayrollSchemes(selected);

  return (
    <Modal title="Схема оплаты" onClose={onClose} wide>
      <div className="space-y-4">
        <Select label="Сотрудник" value={selected} onChange={(e) => setUserId(e.target.value)}>
          {employees.map((u) => (
            <option key={u.id} value={u.id}>{u.full_name}</option>
          ))}
        </Select>
        {q.isLoading && <p className="text-sm text-muted">Загрузка…</p>}
        {q.error && <Alert>{toAppError(q.error).message}</Alert>}
        {q.data && q.data.length === 0 && <EmptyNote>Схем оплаты пока нет</EmptyNote>}
        {q.data && q.data.length > 0 && (
          <ul aria-label="Схемы сотрудника" className="divide-y divide-border rounded-lg border border-border text-sm">
            {q.data.map((s) => (
              <SchemeRow key={s.id} s={s} today={today} />
            ))}
          </ul>
        )}
        {selected && <NewSchemeForm key={selected} userId={selected} today={today} />}
      </div>
    </Modal>
  );
}
