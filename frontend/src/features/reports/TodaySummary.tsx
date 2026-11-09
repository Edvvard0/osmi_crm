import { Link } from "react-router-dom";

import { useActiveLocation } from "@/features/locations/api";
import { formatMoney } from "@/shared/lib/money";

import { useDashboardToday } from "./api";
import { enc, formatPercent } from "./lib";

function Tile({ label, value, to, danger }: { label: string; value: string; to?: string; danger?: boolean }) {
  const body = (
    <>
      <span className={danger ? "block text-xl font-semibold tabular-nums text-danger" : "block text-xl font-semibold tabular-nums"}>{value}</span>
      <span className="block text-sm text-muted">{label}</span>
    </>
  );
  return (
    <li>
      {to ? (
        <Link to={to} className="block rounded-lg border border-border bg-surface p-3 hover:bg-bg">{body}</Link>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-3">{body}</div>
      )}
    </li>
  );
}

/**
 * MG-01: сводка дня. Только при успешном ответе: ошибка и загрузка блок скрывают без уведомлений,
 * чтобы остальные счётчики главной не страдали.
 */
export function TodaySummary() {
  const { value } = useActiveLocation();
  const q = useDashboardToday(value);
  const t = q.data;
  if (!t) return null;

  return (
    <section aria-label="Сводка дня" className="space-y-3">
      <h2 className="text-base font-semibold">Сегодня</h2>
      <ul className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Tile label="Выручка за день" value={formatMoney(t.revenue_today)} />
        <Tile label="Поступления в кассу" value={formatMoney(t.cash_received_today)} to="/cash" />
        <Tile label="Закрыто заказов" value={String(t.orders_closed_today)} />
        <Tile label="Загрузка постов" value={formatPercent(t.post_load_today)} />
        <Tile label="Заказов в работе" value={String(t.orders_open)} to="/orders" />
        <Tile label="Просрочено" value={String(t.overdue)} to="/orders?overdue=true" danger={t.overdue > 0} />
        <Tile label="Готовы к выдаче" value={String(t.ready_for_pickup)} to="/orders?status=ready" />
        <Tile label="Записей на сегодня" value={String(t.appointments_today)} to="/calendar" />
      </ul>
      {t.low_stock_count > 0 && (
        <p className="text-sm">
          <Link to="/stock" className="underline underline-offset-2">Низкий остаток: {t.low_stock_count}</Link>
        </p>
      )}
      {t.mechanics.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-medium text-muted">Механики</h3>
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface text-sm">
            {t.mechanics.map((m) => (
              <li key={m.user.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <div className="min-w-0">
                  <Link to={`/mechanics/${enc(m.user.id)}`} className="break-words font-medium underline underline-offset-2">{m.user.full_name}</Link>
                  <p className="break-words text-muted">
                    {m.active_item ? `${m.active_item.name} · заказ ${m.active_item.order_number}` : "Свободен"}
                  </p>
                </div>
                <p className="whitespace-nowrap text-muted">В работе: {m.items_in_progress} · готово: {m.items_done_today}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
