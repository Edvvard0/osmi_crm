import { useState } from "react";

import { addDays, todayIn } from "@/features/appointments/time";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { parseDecimal } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Alert, Button, Input, Select } from "@/shared/ui/ui";

import { useCreateExpense, useExpenseCategories } from "./api";
import { cashErrorText, toCents } from "./lib";
import { ALL_METHODS, METHOD_LABELS, type PaymentMethod } from "./types";

/** Форма расхода (MG-13). Менеджеру дата ограничена последними 4 днями (сегодня − 3 суток), директору — любая ≤ сегодня. */
export function ExpenseDialog({ locationId, timezone, isDirector, onClose, onDone }: { locationId: string; timezone: string; isDirector: boolean; onClose: () => void; onDone?: () => void }) {
  const today = todayIn(timezone, Date.now());
  const cats = useExpenseCategories();
  const create = useCreateExpense();
  const [categoryId, setCategoryId] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [date, setDate] = useState(today);
  const [description, setDescription] = useState("");
  const [local, setLocal] = useState<Record<string, string>>({});

  const err: AppError | null = create.error ? toAppError(create.error) : null;
  const fe = (n: string) => local[n] ?? (err?.code === "validation_error" ? fieldMessage(err, n) : undefined);
  const hasFields = err?.code === "validation_error" && Object.keys(err.fields).length > 0;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (create.isPending) return;
    const dec = parseDecimal(amount);
    const bad: Record<string, string> = {};
    if (!categoryId) bad.category_id = "Выберите категорию";
    if (!dec || toCents(dec) <= 0) bad.amount = "Введите сумму больше нуля";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) bad.expense_date = "Укажите дату";
    setLocal(bad);
    if (Object.keys(bad).length > 0 || !dec) return;
    create.mutate(
      { location_id: locationId, category_id: categoryId, amount: dec, method, expense_date: date, description: description.trim() || undefined },
      {
        onSuccess: () => {
          onDone?.();
          onClose();
        },
      },
    );
  }

  return (
    <Modal title="Новый расход" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Select label="Категория" value={categoryId} error={fe("category_id")} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">Выберите…</option>
          {(cats.data ?? []).filter((c) => c.is_active).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </Select>
        <Input label="Сумма" inputMode="decimal" autoComplete="off" value={amount} error={fe("amount")} onChange={(e) => setAmount(e.target.value)} />
        <Select label="Способ" value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
          {ALL_METHODS.map((m) => (
            <option key={m} value={m}>{METHOD_LABELS[m]}</option>
          ))}
        </Select>
        <Input
          label="Дата расхода"
          type="date"
          value={date}
          max={today}
          min={isDirector ? undefined : addDays(today, -3)}
          error={fe("expense_date")}
          onChange={(e) => setDate(e.target.value)}
        />
        <Input label="Описание" maxLength={500} value={description} error={fe("description")} onChange={(e) => setDescription(e.target.value)} />
        {err && !hasFields && <Alert>{cashErrorText(err)}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={create.isPending}>Добавить расход</Button>
        </div>
      </form>
    </Modal>
  );
}
