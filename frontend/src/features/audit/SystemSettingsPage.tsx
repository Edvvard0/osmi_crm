import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { parseDecimal } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Checkbox, Input } from "@/shared/ui/ui";

import { useSettings, useUpdateSettings } from "./api";
import type { SettingsPatch, SystemSettings } from "./types";

interface Form {
  discount: string;
  summaryOff: boolean;
  summaryTime: string;
  retention: string;
  hours: string[];
  actions: string[];
}

const fmtNum = (n: number) => String(n).replace(".", ",");

function toForm(s: SystemSettings): Form {
  return {
    discount: s.discount_alert_percent.replace(".", ","),
    summaryOff: s.daily_summary_time === null,
    summaryTime: s.daily_summary_time ?? "21:00",
    retention: String(s.session_retention_days),
    hours: s.heatmap_thresholds.hours.map(fmtNum),
    actions: s.heatmap_thresholds.actions.map(fmtNum),
  };
}

const parseNum = (raw: string): number | null => {
  const s = raw.trim().replace(",", ".");
  return /^\d+(\.\d+)?$/.test(s) ? Number(s) : null;
};

const increasing = (a: number[]) => a[0] < a[1] && a[1] < a[2];

/** Проверка формы → сообщения по полям (ключи — имена полей API) и значения для PATCH. */
export function validate(f: Form): { errors: Record<string, string>; values: SettingsPatch } {
  const errors: Record<string, string> = {};
  const values: SettingsPatch = {};
  const pct = parseDecimal(f.discount);
  if (pct === null || Number(pct) < 1 || Number(pct) > 100) errors.discount_alert_percent = "Порог скидки: от 1 до 100 %";
  else values.discount_alert_percent = pct;

  if (f.summaryOff) values.daily_summary_time = null;
  else if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(f.summaryTime)) errors.daily_summary_time = "Укажите время сводки (чч:мм)";
  else values.daily_summary_time = f.summaryTime;

  const days = /^\d+$/.test(f.retention.trim()) ? Number(f.retention) : NaN;
  if (!(days >= 7 && days <= 365)) errors.session_retention_days = "Срок хранения: от 7 до 365 дней";
  else values.session_retention_days = days;

  const h = f.hours.map(parseNum);
  const a = f.actions.map(parseNum);
  const hOk = h.every((n) => n !== null && n >= 0.5 && n <= 24 && Number.isInteger(n * 2));
  const aOk = a.every((n) => n !== null && Number.isInteger(n) && n >= 1 && n <= 1000);
  if (!hOk) errors.heatmap_hours = "Часы: от 0,5 до 24 с шагом 0,5";
  else if (!increasing(h as number[])) errors.heatmap_hours = "Значения должны строго возрастать";
  if (!aOk) errors.heatmap_actions = "Действия: целые числа от 1 до 1000";
  else if (!increasing(a as number[])) errors.heatmap_actions = "Значения должны строго возрастать";
  if (!errors.heatmap_hours && !errors.heatmap_actions) values.heatmap_thresholds = { hours: h as number[], actions: a as number[] };
  return { errors, values };
}

/** D-09 «Системные настройки» */
export function SystemSettingsPage() {
  const q = useSettings();
  if (q.isLoading) {
    return (
      <div className="mx-auto max-w-xl space-y-3" aria-busy="true" aria-label="Загрузка">
        <h1 className="text-xl font-semibold">Системные настройки</h1>
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-16 animate-pulse rounded border border-border bg-surface" />
        ))}
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="mx-auto max-w-xl space-y-3">
        <h1 className="text-xl font-semibold">Системные настройки</h1>
        <Alert>{toAppError(q.error).message}</Alert>
        <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
      </div>
    );
  }
  return <SettingsForm data={q.data} />;
}

function SettingsForm({ data }: { data: SystemSettings }) {
  const toast = useToast();
  const m = useUpdateSettings();
  const [form, setForm] = useState<Form>(() => toForm(data));
  const [localErr, setLocalErr] = useState<Record<string, string>>({});
  const initial = toForm(data);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);

  // После сохранения/обновления с сервера форма синхронизируется с ответом.
  useEffect(() => {
    setForm(toForm(data));
  }, [data]);

  const err: AppError | null = m.error ? toAppError(m.error) : null;
  const fe = (key: string) => localErr[key] ?? fieldMessage(err, key);
  const patch = (p: Partial<Form>) => {
    setForm((f) => ({ ...f, ...p }));
    setLocalErr({});
    m.reset();
  };
  const setAt = (k: "hours" | "actions", i: number, v: string) => patch({ [k]: form[k].map((x, j) => (j === i ? v : x)) });

  function submit(e: FormEvent) {
    e.preventDefault();
    const { errors, values } = validate(form);
    setLocalErr(errors);
    if (Object.keys(errors).length) return;
    // Отправляем только изменённые ключи.
    const init = toForm(data);
    const body: SettingsPatch = {};
    if (form.discount !== init.discount) body.discount_alert_percent = values.discount_alert_percent;
    if (form.summaryOff !== init.summaryOff || (!form.summaryOff && form.summaryTime !== init.summaryTime)) body.daily_summary_time = values.daily_summary_time;
    if (form.retention !== init.retention) body.session_retention_days = values.session_retention_days;
    if (JSON.stringify([form.hours, form.actions]) !== JSON.stringify([init.hours, init.actions])) body.heatmap_thresholds = values.heatmap_thresholds;
    m.mutate(body, { onSuccess: () => toast.push("success", "Настройки сохранены") });
  }

  const showAlert = err && !Object.keys(err.fields).length && err.code !== "validation_error";
  const hmErr = fe("heatmap_hours") ?? fe("heatmap_actions") ?? fe("heatmap_thresholds");
  const ht = validate(form).values.heatmap_thresholds;

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Системные настройки</h1>
        <Link to="/cash" className="text-sm text-accent underline">Категории расходов</Link>
      </div>

      <form onSubmit={submit} className="space-y-6" noValidate>
        <section className="space-y-2" aria-labelledby="ss-discount">
          <h2 id="ss-discount" className="text-base font-semibold">Скидки</h2>
          <Input label="Порог скидки для уведомления, %" inputMode="decimal" value={form.discount} onChange={(e) => patch({ discount: e.target.value })} error={fe("discount_alert_percent")} />
          <p className="text-xs text-muted">При скидке в заказе от этого значения руководитель получает уведомление.</p>
        </section>

        <section className="space-y-2" aria-labelledby="ss-summary">
          <h2 id="ss-summary" className="text-base font-semibold">Ежедневная сводка</h2>
          <Checkbox label="Отключено" checked={form.summaryOff} onChange={(e) => patch({ summaryOff: e.target.checked })} />
          {!form.summaryOff && (
            <Input label="Время сводки" type="time" value={form.summaryTime} onChange={(e) => patch({ summaryTime: e.target.value })} error={fe("daily_summary_time")} />
          )}
        </section>

        <section className="space-y-2" aria-labelledby="ss-sessions">
          <h2 id="ss-sessions" className="text-base font-semibold">Сессии</h2>
          <Input label="Срок хранения сессий, дней" inputMode="numeric" value={form.retention} onChange={(e) => patch({ retention: e.target.value })} error={fe("session_retention_days")} />
          <p className="text-xs text-muted">От 7 до 365. Срок жизни самого входа (14 суток) не меняется.</p>
        </section>

        <section className="space-y-3" aria-labelledby="ss-heat">
          <h2 id="ss-heat" className="text-base font-semibold">Тепловая карта</h2>
          <fieldset className="space-y-1">
            <legend className="mb-1 text-sm text-muted">Механик — пороги по часам работы</legend>
            <div className="grid grid-cols-3 gap-2">
              {form.hours.map((v, i) => (
                <Input key={i} label={`Порог ${i + 1}, ч`} inputMode="decimal" value={v} onChange={(e) => setAt("hours", i, e.target.value)} />
              ))}
            </div>
          </fieldset>
          <fieldset className="space-y-1">
            <legend className="mb-1 text-sm text-muted">Менеджер — пороги по числу действий за день</legend>
            <div className="grid grid-cols-3 gap-2">
              {form.actions.map((v, i) => (
                <Input key={i} label={`Порог ${i + 1}, действий`} inputMode="numeric" value={v} onChange={(e) => setAt("actions", i, e.target.value)} />
              ))}
            </div>
          </fieldset>
          {hmErr && <p role="alert" className="text-xs text-danger">{hmErr}</p>}
          <HeatPreview label="Механик" unit="ч" values={ht?.hours} />
          <HeatPreview label="Менеджер" unit="" values={ht?.actions} />
        </section>

        {showAlert && <Alert>{err.message}</Alert>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={m.isPending} disabled={!dirty}>Сохранить</Button>
          {data.updated_at && (
            <p className="text-xs text-muted">
              Изменено {new Date(data.updated_at).toLocaleString("ru-RU")}
              {data.updated_by ? `, ${data.updated_by.full_name}` : ""}
            </p>
          )}
        </div>
      </form>
    </div>
  );
}

/** Превью пяти уровней: 0 и четыре диапазона между порогами. */
function HeatPreview({ label, unit, values }: { label: string; unit: string; values?: number[] }) {
  const u = unit ? ` ${unit}` : "";
  const t = values?.map(fmtNum);
  const names = t ? ["0", `до ${t[0]}${u}`, `${t[0]}–${t[1]}${u}`, `${t[1]}–${t[2]}${u}`, `больше ${t[2]}${u}`] : ["—", "—", "—", "—", "—"];
  return (
    <div className="space-y-1" aria-label={`Превью: ${label}`}>
      <p className="text-xs text-muted">{label}</p>
      <div className="grid grid-cols-5 gap-1 text-center text-[11px] leading-tight">
        {names.map((n, i) => (
          <div key={i} className="rounded border border-border px-1 py-2">
            <div className="mb-1 h-3 rounded bg-accent" style={{ opacity: i === 0 ? 0.06 : 0.2 + i * 0.2 }} aria-hidden />
            {n}
          </div>
        ))}
      </div>
    </div>
  );
}
