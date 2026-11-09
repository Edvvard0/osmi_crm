import clsx from "clsx";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { safeZone } from "@/features/appointments/time";
import { useLocations } from "@/features/locations/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { Alert, Button, Input, Select } from "@/shared/ui/ui";

import { type AuditFilters, useAuditLog, useAuditMeta, useUserOptions } from "./api";
import type { AuditEntry } from "./types";

const FILTER_KEYS: (keyof AuditFilters)[] = ["date_from", "date_to", "user_id", "action", "entity_type", "location_id"];

/** Время записи — в поясе точки записи, без точки — в поясе браузера. */
export function formatAuditTime(iso: string, tz: string | null | undefined): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: tz ? safeZone(tz) : undefined,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(d);
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "да" : "нет";
  if (typeof v === "string" || typeof v === "number") return String(v);
  return JSON.stringify(v);
}

function isDiff(v: unknown): v is { old: unknown; new: unknown } {
  return typeof v === "object" && v !== null && !Array.isArray(v) && "old" in v && "new" in v;
}

/** Ссылку строим только из entity_path сервера и только внутри приложения. */
const safePath = (p: string | null) => (p && p.startsWith("/") && !p.startsWith("//") ? p : null);

/** D-08 «Журнал действий» */
export function AuditPage() {
  const [sp, setSp] = useSearchParams();
  const filters = Object.fromEntries(FILTER_KEYS.map((k) => [k, sp.get(k) ?? ""])) as unknown as AuditFilters;
  const meta = useAuditMeta();
  const locs = useLocations();
  const users = useUserOptions();
  const q = useAuditLog(filters);

  function set(k: keyof AuditFilters, v: string) {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  }
  const reset = () => setSp(new URLSearchParams(), { replace: true });
  const hasFilters = FILTER_KEYS.some((k) => filters[k]);
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const total = q.data?.pages[0]?.total ?? 0;
  const err: AppError | null = q.error ? toAppError(q.error) : null;
  const actionLabel = (v: string) => meta.data?.actions.find((a) => a.value === v)?.label ?? v;
  const typeLabel = (v: string) => meta.data?.entity_types.find((a) => a.value === v)?.label ?? v;
  const filterErr = err?.code === "validation_error";

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Журнал действий</h1>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Input label="С даты" type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} error={fieldMessage(err, "date_from")} />
        <Input label="По дату" type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} error={fieldMessage(err, "date_to")} />
        <Select label="Сотрудник" value={filters.user_id} onChange={(e) => set("user_id", e.target.value)}>
          <option value="">Все</option>
          <option value="system">Система</option>
          {(users.data?.items ?? []).map((u) => (
            <option key={u.id} value={u.id}>{u.full_name}</option>
          ))}
        </Select>
        <Select label="Действие" value={filters.action} onChange={(e) => set("action", e.target.value)} error={fieldMessage(err, "action")}>
          <option value="">Все</option>
          {(meta.data?.actions ?? []).map((a) => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </Select>
        <Select label="Тип объекта" value={filters.entity_type} onChange={(e) => set("entity_type", e.target.value)} error={fieldMessage(err, "entity_type")}>
          <option value="">Все</option>
          {(meta.data?.entity_types ?? []).map((a) => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </Select>
        <Select label="Точка" value={filters.location_id} onChange={(e) => set("location_id", e.target.value)}>
          <option value="">Все</option>
          {(locs.data ?? []).map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </Select>
      </div>
      {hasFilters && (
        <Button variant="ghost" onClick={reset}>Сбросить фильтры</Button>
      )}

      {q.isLoading ? (
        <ul aria-label="Загрузка" aria-busy="true" className="space-y-2">
          {Array.from({ length: 8 }, (_, i) => (
            <li key={i} className="h-12 animate-pulse rounded border border-border bg-surface" />
          ))}
        </ul>
      ) : q.isError && items.length === 0 ? (
        <div className="space-y-2">
          <Alert>{filterErr ? "Проверьте фильтры" : (err?.message ?? "")}</Alert>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      ) : items.length === 0 ? (
        <div className="space-y-2 py-8 text-center">
          <p className="text-sm text-muted">Записей по выбранным фильтрам нет</p>
          {hasFilters && <Button variant="secondary" onClick={reset}>Сбросить фильтры</Button>}
        </div>
      ) : (
        <>
          <p className="text-xs text-muted">Показано {items.length} из {total}</p>
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
            {items.map((e) => (
              <Row key={e.id} e={e} actionLabel={actionLabel} typeLabel={typeLabel} />
            ))}
          </ul>
          {q.isError && (
            <div className="space-y-2">
              <Alert>{err?.message ?? ""}</Alert>
              <Button variant="secondary" onClick={() => void q.fetchNextPage()}>Повторить</Button>
            </div>
          )}
          {q.hasNextPage ? (
            <Button variant="secondary" loading={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>Показать ещё</Button>
          ) : (
            items.length < total && <p className="text-xs text-muted">Глубже листать нельзя — сузьте фильтры.</p>
          )}
        </>
      )}
    </div>
  );
}

function Row({ e, actionLabel, typeLabel }: { e: AuditEntry; actionLabel: (v: string) => string; typeLabel: (v: string) => string }) {
  const [open, setOpen] = useState(false);
  const path = safePath(e.entity_path);
  const objLabel = e.entity_label ?? (e.entity_id ? `${typeLabel(e.entity_type)} · ${e.entity_id.slice(0, 8)}` : typeLabel(e.entity_type));
  const changes = e.changes ? Object.entries(e.changes) : [];
  const detailsId = `audit-${e.id}`;
  return (
    <li>
      <div className="grid gap-x-3 gap-y-1 px-3 py-2 text-sm md:grid-cols-[11rem_10rem_9rem_minmax(0,1fr)_8rem_2rem] md:items-center">
        <time dateTime={e.created_at} className="text-xs text-muted md:text-sm md:text-fg">{formatAuditTime(e.created_at, e.location?.timezone)}</time>
        <span className="truncate">{e.user?.full_name ?? "Система"}</span>
        <span className="font-medium">{actionLabel(e.action)}</span>
        <span className="min-w-0 truncate">
          {path ? <Link to={path} className="text-accent underline">{objLabel}</Link> : objLabel}
        </span>
        <span className="truncate text-muted">{e.location?.name ?? "—"}</span>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={detailsId}
          aria-label={open ? "Скрыть подробности" : "Показать подробности"}
          onClick={() => setOpen((v) => !v)}
          className="justify-self-start rounded px-2 py-1 text-muted hover:text-fg md:justify-self-end"
        >
          <span aria-hidden className={clsx("inline-block transition-transform", open && "rotate-90")}>›</span>
        </button>
      </div>
      {open && (
        <div id={detailsId} className="space-y-2 border-t border-border bg-bg px-3 py-3 text-sm">
          {changes.length > 0 ? (
            <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[12rem_1fr]">
              {changes.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="break-words text-muted">{k}</dt>
                  <dd className="break-words">{isDiff(v) ? <>{fmtVal(v.old)} → {fmtVal(v.new)}</> : fmtVal(v)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-muted">Изменений не записано</p>
          )}
          <p className="break-words text-xs text-muted">
            IP: {e.ip ?? "—"} · Устройство: {e.user_agent ?? "—"}
          </p>
        </div>
      )}
    </li>
  );
}
