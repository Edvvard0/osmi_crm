/** Типы модуля 10 по docs/api-contract-m10.md. Деньги/часы/проценты — строки-десятичные. */
import type { Department } from "@/shared/api/types";

export interface LocationRef { id: string; name: string }
export interface UserRef { id: string; full_name: string }

/* ---------- Дашборд директора (D-01) ---------- */

export type KpiKind = "money" | "count" | "percent";
export interface Kpi { kind: KpiKind; value: string; previous: string; delta: string | null }

export interface AttentionOrder { id: string; number: string; location: LocationRef; value: string }

export interface Dashboard {
  period: { date_from: string; date_to: string; previous_from: string; previous_to: string };
  location_id: string | null;
  kpis: {
    revenue: Kpi;
    cash_received: Kpi;
    orders_closed: Kpi;
    average_check: Kpi;
    post_load: Kpi;
    detailing_share: Kpi;
    conversion: Kpi;
    new_clients: Kpi;
    repeat_clients: Kpi;
  };
  revenue_series: {
    date: string;
    total: string;
    by_location: { location_id: string; total: string }[];
    by_department: { service_works: string; detailing_works: string; parts: string };
  }[];
  locations: { location: LocationRef; revenue: string; orders_closed: number; average_check: string; post_load: string; detailing_share: string }[];
  top_services: { service_id: string | null; name: string; quantity: string; revenue: string }[];
  attention: {
    refunds: { count: number; total: string };
    big_discounts: { count: number; threshold: string; items: AttentionOrder[] };
    overdue_orders: { count: number; items: AttentionOrder[] };
    low_stock: {
      count: number;
      items: { location: LocationRef; part: { id: string; sku: string; name: string }; quantity: string; min_quantity: string }[];
    };
  };
}

/* ---------- Сводка точки (MG-16) и сводка дня (MG-01) ---------- */

export type SummaryPeriod = "day" | "week" | "month";

export interface LocationSummary {
  location: LocationRef;
  date_from: string;
  date_to: string;
  revenue: string;
  orders_closed: number;
  average_check: string;
  post_load: string;
  series: { date: string; revenue: string; orders: number }[];
  mechanics: { user: UserRef; items_done: number; norm_hours: string; actual_hours: string; efficiency: string | null; works_amount: string }[];
}

export interface DashboardToday {
  server_time: string;
  location: LocationRef;
  date: string;
  revenue_today: string;
  cash_received_today: string;
  orders_closed_today: number;
  orders_open: number;
  overdue: number;
  ready_for_pickup: number;
  appointments_today: number;
  post_load_today: string;
  low_stock_count: number;
  mechanics: {
    user: UserRef;
    active_item: { item_id: string; name: string; order_number: string } | null;
    items_in_progress: number;
    items_done_today: number;
  }[];
}

/* ---------- Отчёты (D-02) ---------- */

export type ReportId = "revenue" | "services" | "mechanics" | "clients" | "stock" | "expenses" | "profit";
export type ReportColumnKind = "text" | "money" | "hours" | "count" | "percent" | "date";
export interface ReportColumn { key: string; title: string; kind: ReportColumnKind }
export interface ReportChart { type: "line" | "bar"; x: string; series: { key: string; title: string }[] }
export type ReportRow = Record<string, string | null>;

export interface Report {
  id: ReportId;
  title: string;
  date_from: string;
  date_to: string;
  location_id: string | null;
  columns: ReportColumn[];
  rows: ReportRow[];
  totals: ReportRow | null;
  chart: ReportChart | null;
  truncated?: boolean;
  generated_at: string;
}

export type ExportFormat = "xlsx" | "csv";

/* ---------- Зарплата (D-03) ---------- */

export type PayrollSchemeType = "percent_of_works" | "per_norm_hour" | "fixed_plus_percent" | "fixed";

export interface PayrollScheme {
  id: string;
  user: UserRef;
  scheme_type: PayrollSchemeType;
  percent: string | null;
  norm_hour_rate: string | null;
  fixed_monthly: string | null;
  department: Department | null;
  valid_from: string;
  valid_to: string | null;
  is_current: boolean;
  description: string;
  created_by: UserRef;
  created_at: string;
}

export interface PayrollAdjustment {
  id: string;
  user: UserRef;
  month: string;
  amount: string;
  reason: string;
  created_by: UserRef;
  created_at: string;
}

export interface PayrollRow {
  user: UserRef;
  locations: LocationRef[];
  scheme_summary: string;
  items_done: number;
  norm_hours: string;
  base_amount: string;
  accrued: string;
  adjustments_total: string;
  total: string;
  items_without_scheme: number;
}

export interface PayrollSheet {
  month: string;
  location_id: string | null;
  rows: PayrollRow[];
  totals: { items_done: number; norm_hours: string; base_amount: string; accrued: string; adjustments_total: string; total: string };
}

export interface PayrollItemLine {
  item_id: string;
  order: { id: string; number: string };
  closed_at: string;
  name: string;
  department: Department;
  quantity: string;
  norm_hours_total: string;
  item_net: string;
  scheme_id: string | null;
  amount: string;
}
export interface PayrollFixedLine { scheme_id: string; days: number; days_in_month: number; amount: string }

export interface PayrollDetail {
  row: PayrollRow;
  items: PayrollItemLine[];
  fixed: PayrollFixedLine[];
  adjustments: PayrollAdjustment[];
  schemes: PayrollScheme[];
}

/* ---------- Заработок механика (M-07) ---------- */

export interface MyEarnings {
  month: string;
  accrued: string;
  adjustments_total: string;
  total: string;
  items_done: number;
  norm_hours: string;
  actual_hours: string;
  adjustments: { amount: string; reason: string; created_at: string }[];
  awaiting_close: { items_count: number; norm_hours: string };
  days: {
    date: string;
    items: {
      item_id: string;
      order: { id: string; number: string };
      plate_number: string | null;
      name: string;
      norm_hours_total: string;
      actual_minutes: number;
      finished_at: string;
    }[];
  }[];
  server_time: string;
}

/* ---------- Тепловая карта ---------- */

export type ActivityKind = "hours" | "actions";
export type ActivityLevel = 0 | 1 | 2 | 3 | 4;

export interface ActivityDay {
  date: string;
  minutes: number | null;
  hours: string | null;
  actions: number | null;
  works_count: number;
  level: ActivityLevel;
  order_numbers: string[];
}

export interface ActivityHeatmapData {
  user: UserRef;
  kind: ActivityKind;
  from: string;
  to: string;
  timezone: string;
  first_day: string;
  thresholds: number[];
  days: ActivityDay[];
  summary: {
    working_days: number;
    total_hours: string | null;
    total_actions: number | null;
    average_per_working_day: string;
    longest_streak_days: number;
  };
}

export interface HoursEntry {
  order: { id: string; number: string };
  plate_number: string | null;
  item_id: string;
  item_name: string;
  started_at: string;
  ended_at: string | null;
  minutes: number;
}
export interface ActionEntry {
  at: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  label: string;
  order_number: string | null;
}
export interface ActivityDetails {
  user: UserRef;
  kind: ActivityKind;
  days: {
    date: string;
    total_minutes: number | null;
    actions: number | null;
    truncated: boolean;
    entries: (HoursEntry | ActionEntry)[];
  }[];
}
