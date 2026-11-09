import { QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "@/app/queryClient";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { ActivityHeatmap } from "@/features/reports/ActivityHeatmap";
import { ActivityPanel } from "@/features/reports/ActivityPanel";
import { DirectorDashboard } from "@/features/reports/DirectorDashboard";
import { EarningsPage } from "@/features/reports/EarningsPage";
import { LocationReportPage } from "@/features/reports/LocationReportPage";
import { MechanicActivityPage } from "@/features/reports/MechanicActivityPage";
import { PayrollPage } from "@/features/reports/PayrollPage";
import { ReportsPage } from "@/features/reports/ReportsPage";
import { TodaySummary } from "@/features/reports/TodaySummary";
import { errorMessages } from "@/features/reports/errors";
import {
  formatCell,
  formatDelta,
  formatDuration,
  formatMonth,
  formatSigned,
  parseSigned,
  plural,
  reportErrorText,
  shiftMonth,
} from "@/features/reports/lib";
import type {
  ActivityDay,
  ActivityHeatmapData,
  Dashboard,
  DashboardToday,
  Kpi,
  LocationSummary,
  MyEarnings,
  PayrollDetail,
  PayrollSheet,
  Report,
} from "@/features/reports/types";
import { UserPage } from "@/pages/users/UserPage";
import { AppError, ERROR_MESSAGES } from "@/shared/api/errors";
import type { Role } from "@/shared/api/types";
import { ToastProvider } from "@/shared/ui/toast";

import { type Handler, LOC1, LOC2, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

afterEach(() => {
  vi.restoreAllMocks();
});

/** Пробелы (в том числе неразрывные) в обычные: так проще сравнивать форматированные суммы. */
const norm = (s: string | null | undefined) => (s ?? "").replace(/\s/g, " ");

/* ---------- Фикстуры ---------- */

const MECH = { id: "m1", full_name: "Пётр Механик" };

function day(date: string, level: 0 | 1 | 2 | 3 | 4, minutes: number, works: number): ActivityDay {
  return { date, minutes, hours: (minutes / 60).toFixed(2), actions: null, works_count: works, level, order_numbers: [] };
}

const HEAT: ActivityHeatmapData = {
  user: MECH,
  kind: "hours",
  from: "2026-11-02",
  to: "2026-11-09",
  timezone: "Europe/Moscow",
  first_day: "2026-01-01",
  thresholds: [2, 5, 8],
  days: [
    day("2026-11-02", 0, 0, 0),
    day("2026-11-03", 2, 440, 3),
    day("2026-11-04", 4, 600, 5),
    day("2026-11-05", 1, 60, 1),
    day("2026-11-06", 0, 0, 0),
    day("2026-11-07", 0, 0, 0),
    day("2026-11-08", 0, 0, 0),
    day("2026-11-09", 0, 0, 0),
  ],
  summary: { working_days: 3, total_hours: "18.33", total_actions: null, average_per_working_day: "6.11", longest_streak_days: 3 },
};

const detailsOf = (date: string | null) => ({
  user: MECH,
  kind: "hours",
  days: [
    {
      date: date ?? "2026-11-09",
      total_minutes: 75,
      actions: null,
      truncated: false,
      entries: [
        {
          order: { id: "o1", number: "MSK1-000001" },
          plate_number: "А123ВС777",
          item_id: "i1",
          item_name: "Замена масла",
          started_at: "2026-11-04T06:00:00Z",
          ended_at: "2026-11-04T07:15:00Z",
          minutes: 75,
        },
      ],
    },
  ],
});

const kpi = (kind: Kpi["kind"], value: string, previous: string, delta: string | null): Kpi => ({ kind, value, previous, delta });

const DASH: Dashboard = {
  period: { date_from: "2026-11-01", date_to: "2026-11-09", previous_from: "2026-10-23", previous_to: "2026-10-31" },
  location_id: null,
  kpis: {
    revenue: kpi("money", "250000.00", "200000.00", "25.00"),
    cash_received: kpi("money", "240000.00", "190000.00", "26.32"),
    orders_closed: kpi("count", "40", "35", "14.29"),
    average_check: kpi("money", "6250.00", "5714.00", "9.38"),
    post_load: kpi("percent", "62.50", "65.70", "-3.20"),
    detailing_share: kpi("percent", "12.00", "10.00", "2.00"),
    conversion: kpi("percent", "70.00", "70.00", null),
    new_clients: kpi("count", "9", "7", "28.57"),
    repeat_clients: kpi("count", "20", "18", "11.11"),
  },
  revenue_series: [
    { date: "2026-11-01", total: "1000.00", by_location: [], by_department: { service_works: "600.00", detailing_works: "300.00", parts: "100.00" } },
    { date: "2026-11-02", total: "2000.00", by_location: [], by_department: { service_works: "1200.00", detailing_works: "600.00", parts: "200.00" } },
  ],
  locations: [{ location: { id: "l1", name: "Москва-1" }, revenue: "150000.00", orders_closed: 25, average_check: "6000.00", post_load: "60.00", detailing_share: "10.00" }],
  top_services: [{ service_id: "s1", name: "Замена масла", quantity: "30.000", revenue: "90000.00" }],
  attention: {
    refunds: { count: 1, total: "500.00" },
    big_discounts: { count: 0, threshold: "20.00", items: [] },
    overdue_orders: { count: 1, items: [{ id: "o9", number: "MSK1-000009", location: { id: "l1", name: "Москва-1" }, value: "2026-11-05T09:00:00Z" }] },
    low_stock: { count: 1, items: [{ location: { id: "l1", name: "Москва-1" }, part: { id: "p1", sku: "F-1", name: "Фильтр масляный" }, quantity: "1.000", min_quantity: "5.000" }] },
  },
};

const TODAY: DashboardToday = {
  server_time: "2026-11-09T09:00:00Z",
  location: { id: "l1", name: "Москва-1" },
  date: "2026-11-09",
  revenue_today: "15000.00",
  cash_received_today: "12000.00",
  orders_closed_today: 4,
  orders_open: 7,
  overdue: 2,
  ready_for_pickup: 1,
  appointments_today: 5,
  post_load_today: "55.00",
  low_stock_count: 3,
  mechanics: [{ user: MECH, active_item: { item_id: "i1", name: "Замена масла", order_number: "MSK1-000001" }, items_in_progress: 1, items_done_today: 2 }],
};

const SUMMARY: LocationSummary = {
  location: { id: "l1", name: "Москва-1" },
  date_from: "2026-11-09",
  date_to: "2026-11-09",
  revenue: "123456.00",
  orders_closed: 8,
  average_check: "15432.00",
  post_load: "48.00",
  series: [
    { date: "2026-11-08", revenue: "1000.00", orders: 1 },
    { date: "2026-11-09", revenue: "2000.00", orders: 2 },
  ],
  mechanics: [{ user: MECH, items_done: 6, norm_hours: "9.00", actual_hours: "10.50", efficiency: "85.71", works_amount: "45000.00" }],
};

const REVENUE: Report = {
  id: "revenue",
  title: "Выручка",
  date_from: "2026-11-01",
  date_to: "2026-11-09",
  location_id: null,
  columns: [
    { key: "location", title: "Точка", kind: "text" },
    { key: "revenue", title: "Выручка", kind: "money" },
  ],
  rows: [{ location: "Москва-1", revenue: "150000.00" }],
  totals: { revenue: "150000.00" },
  chart: { type: "bar", x: "location", series: [{ key: "revenue", title: "Выручка" }] },
  generated_at: "2026-11-09T09:00:00Z",
};

const MECHANICS_REPORT: Report = {
  id: "mechanics",
  title: "Механики",
  date_from: "2026-11-01",
  date_to: "2026-11-09",
  location_id: null,
  columns: [
    { key: "mechanic", title: "Механик", kind: "text" },
    { key: "items_done", title: "Работ", kind: "count" },
  ],
  rows: [{ mechanic: "Пётр Механик", user_id: "m1", items_done: "6" }],
  totals: null,
  chart: null,
  generated_at: "2026-11-09T09:00:00Z",
};

const ROW = {
  user: MECH,
  locations: [{ id: "l1", name: "Москва-1" }],
  scheme_summary: "40% от работ",
  items_done: 12,
  norm_hours: "18.50",
  base_amount: "90000.00",
  accrued: "36000.00",
  adjustments_total: "-500.00",
  total: "35500.00",
  items_without_scheme: 2,
};

const sheetOf = (month: string | null): PayrollSheet => ({
  month: month ?? "2026-11",
  location_id: null,
  rows: [ROW],
  totals: { items_done: 12, norm_hours: "18.50", base_amount: "90000.00", accrued: "36000.00", adjustments_total: "-500.00", total: "35500.00" },
});

const PAYROLL_DETAIL: PayrollDetail = {
  row: ROW,
  items: [
    {
      item_id: "i1",
      order: { id: "o1", number: "MSK1-000001" },
      closed_at: "2026-11-04T10:00:00Z",
      name: "Замена масла",
      department: "service",
      quantity: "1.000",
      norm_hours_total: "1.00",
      item_net: "3000.00",
      scheme_id: null,
      amount: "0.00",
    },
  ],
  fixed: [],
  adjustments: [],
  schemes: [],
};

const earningsOf = (month: string | null): MyEarnings => ({
  month: month ?? "2026-11",
  accrued: "42000.00",
  adjustments_total: "1500.00",
  total: "43500.00",
  items_done: 5,
  norm_hours: "7.50",
  actual_hours: "8.25",
  adjustments: [{ amount: "1500.00", reason: "Премия за качество", created_at: "2026-11-05T10:00:00Z" }],
  awaiting_close: { items_count: 2, norm_hours: "1.50" },
  days: [
    {
      date: "2026-11-04",
      items: [
        {
          item_id: "i1",
          order: { id: "o1", number: "MSK1-000001" },
          plate_number: "А123ВС777",
          name: "Замена масла",
          norm_hours_total: "1.00",
          actual_minutes: 75,
          finished_at: "2026-11-04T10:00:00Z",
        },
      ],
    },
  ],
  server_time: "2026-11-09T09:00:00Z",
});

/* ---------- Окружение ---------- */

function world(role: Role, over: Record<string, Handler> = {}, userOver: Partial<ReturnType<typeof makeUser>> = {}) {
  const user = makeUser(role, userOver);
  return mockApi({
    "POST /auth/refresh": () => json(200, session(user)),
    "GET /locations": () => json(200, role === "director" ? [LOC1, LOC2] : [LOC1]),
    "GET /users/m1/activity-heatmap": () => json(200, HEAT),
    "GET /users/m1/activity-details": (r) => json(200, detailsOf(r.query.get("date_from"))),
    [`GET /users/${user.id}/activity-heatmap`]: () => json(200, HEAT),
    [`GET /users/${user.id}/activity-details`]: (r) => json(200, detailsOf(r.query.get("date_from"))),
    ...over,
  });
}

function AuthGate({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  return user ? <>{children}</> : null;
}

/** Экран монтируется напрямую (без App): тест не зависит от маршрутов других модулей. */
function open(ui: ReactNode, path = "/", route = "*") {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <AuthGate>
              <Routes>
                <Route path={route} element={ui} />
              </Routes>
            </AuthGate>
          </MemoryRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const bodyOf = (f: ReturnType<typeof mockApi>, key: string) => JSON.parse(String(calls(f, key)[0][1]?.body)) as Record<string, unknown>;
const cell = (date: string) => document.querySelector<HTMLElement>(`[data-date="${date}"]`) as HTMLElement;

/* ---------- Чистые функции ---------- */

describe("модуль 10: форматирование", () => {
  it("изменение к прошлому периоду: стрелка, знак, п.п. для процентов, пусто → тире", () => {
    expect(formatDelta("money", "12.5")).toEqual({ text: "▲ 12,50 %", sign: 1 });
    expect(formatDelta("percent", "-3.2")).toEqual({ text: "▼ 3,20 п.п.", sign: -1 });
    expect(formatDelta("count", "0.00")).toEqual({ text: "0 %", sign: 0 });
    expect(formatDelta("money", null)).toEqual({ text: "—", sign: 0 });
  });

  it("длительность, склонение, месяцы", () => {
    expect(norm(formatDuration(440))).toBe("7 ч 20 мин");
    expect(norm(formatDuration(45))).toBe("45 мин");
    expect(norm(formatDuration(120))).toBe("2 ч");
    expect(norm(formatDuration(0))).toBe("0 мин");
    expect([1, 2, 5, 11, 21].map((n) => plural(n, "работа", "работы", "работ"))).toEqual(["работа", "работы", "работ", "работ", "работа"]);
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(formatMonth("2026-11")).toBe("ноябрь 2026");
  });

  it("сумма со знаком: минус и пробелы разбираются, ноль и мусор отклоняются", () => {
    expect(parseSigned("−500")).toBe("-500.00");
    expect(parseSigned("-500,5")).toBe("-500.50");
    expect(parseSigned("+1 000,5")).toBe("1000.50");
    expect(parseSigned("0")).toBeNull();
    expect(parseSigned("abc")).toBeNull();
    expect(parseSigned("")).toBeNull();
    expect(norm(formatSigned("1000.00"))).toBe("+1 000,00 ₽");
    expect(norm(formatSigned("-500.00"))).toBe("−500,00 ₽");
  });

  it("ячейки отчёта по типу колонки; значения не интерпретируются как разметка", () => {
    expect(norm(formatCell("1500.5", "money"))).toBe("1 500,50 ₽");
    expect(norm(formatCell("1.5", "hours"))).toBe("1,50 ч");
    expect(norm(formatCell("12.50", "percent"))).toBe("12,50 %");
    expect(formatCell("3.500", "count")).toBe("3,5");
    expect(formatCell("2026-11-09", "date")).toBe("09.11.2026");
    expect(formatCell(null, "money")).toBe("—");
    expect(formatCell("<b>x</b>", "text")).toBe("<b>x</b>");
  });

  it("ошибки: serverный текст не показывается, поля периода объяснены, есть scheme_overlap", () => {
    expect(reportErrorText(new AppError("validation_error", 422, { date_to: "SQLSTATE" }))).toBe("Конец периода не раньше начала, не более 366 суток");
    expect(reportErrorText(new AppError("rate_limited", 429, {}))).toBe(ERROR_MESSAGES.rate_limited);
    expect(errorMessages.scheme_overlap).toBeTruthy();
    expect(ERROR_MESSAGES.scheme_overlap).toBe(errorMessages.scheme_overlap);
  });
});

/* ---------- Тепловая карта ---------- */

describe("тепловая карта активности", () => {
  it("уровни, подписи дней, итоги периода", async () => {
    world("manager");
    open(<ActivityHeatmap userId="m1" from="2026-11-02" to="2026-11-09" variant="desktop" />);
    await waitFor(() => expect(cell("2026-11-04")).toBeTruthy());

    expect(cell("2026-11-04").dataset.level).toBe("4");
    expect(cell("2026-11-03").dataset.level).toBe("2");
    expect(cell("2026-11-05").dataset.level).toBe("1");
    expect(cell("2026-11-02").dataset.level).toBe("0");
    expect(norm(cell("2026-11-04").getAttribute("aria-label"))).toBe("Среда, 4 ноября 2026 · 10 ч · 5 работ");
    expect(norm(cell("2026-11-03").getAttribute("aria-label"))).toBe("Вторник, 3 ноября 2026 · 7 ч 20 мин · 3 работы");
    expect(norm(cell("2026-11-02").getAttribute("aria-label"))).toBe("Понедельник, 2 ноября 2026 · Нет активности");
    // Смысл не только в цвете: та же подпись в title.
    expect(cell("2026-11-04")).toHaveAttribute("title", cell("2026-11-04").getAttribute("aria-label")!);

    expect(screen.getByText("Рабочих дней").nextElementSibling).toHaveTextContent("3");
    expect(norm(screen.getByText("Всего часов").nextElementSibling?.textContent)).toBe("18,33 ч");
    expect(screen.getByText("3 дня подряд")).toBeInTheDocument();
  });

  it("клавиатура: стрелки, Home и End двигают фокус по дням, за пределы не выходят", async () => {
    world("manager");
    const picked: string[] = [];
    open(<ActivityHeatmap userId="m1" from="2026-11-02" to="2026-11-09" variant="desktop" onSelect={(d) => picked.push(d)} />);
    await waitFor(() => expect(cell("2026-11-04")).toBeTruthy());
    const u = userEvent.setup();

    await u.click(cell("2026-11-04"));
    expect(picked).toEqual(["2026-11-04"]);
    await u.keyboard("{ArrowDown}");
    expect(cell("2026-11-05")).toHaveFocus();
    await u.keyboard("{ArrowUp}{ArrowUp}");
    expect(cell("2026-11-03")).toHaveFocus();
    await u.keyboard("{Home}");
    expect(cell("2026-11-02")).toHaveFocus();
    await u.keyboard("{ArrowLeft}");
    expect(cell("2026-11-02")).toHaveFocus();
    await u.keyboard("{End}");
    expect(cell("2026-11-09")).toHaveFocus();
    // Только одна ячейка в порядке табуляции.
    expect(document.querySelectorAll('[data-date][tabindex="0"]')).toHaveLength(1);
  });

  it("переключатель «Таблица»: дни с активностью по убыванию даты", async () => {
    world("manager");
    open(<ActivityHeatmap userId="m1" from="2026-11-02" to="2026-11-09" variant="desktop" />);
    await waitFor(() => expect(cell("2026-11-04")).toBeTruthy());
    const u = userEvent.setup();

    await u.click(screen.getByRole("button", { name: "Таблица" }));
    const rows = within(await screen.findByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(4); // заголовок + 3 дня
    expect(rows[1]).toHaveTextContent("5 ноября 2026");
    expect(rows[3]).toHaveTextContent("3 ноября 2026");
    expect(document.querySelector("[data-date]")).toBeNull();
  });

  it("панель: выбор дня запрашивает его записи; ошибка доступа не прячется за пустой картой", async () => {
    const f = world("manager");
    open(<ActivityPanel userId="m1" defaultRange="12m" />);
    const u = userEvent.setup();
    await waitFor(() => expect(cell("2026-11-04")).toBeTruthy());

    await u.click(cell("2026-11-04"));
    expect(await screen.findByRole("heading", { name: "Среда, 4 ноября 2026" })).toBeInTheDocument();
    await waitFor(() => expect(calls(f, "GET /users/m1/activity-details").some(([i]) => String(i).includes("date_from=2026-11-04"))).toBe(true));
    expect(await screen.findByText("Замена масла")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Заказ MSK1-000001" })).toHaveAttribute("href", "/orders/o1");
  });
});

/* ---------- D-01 дашборд директора ---------- */

describe("D-01 дашборд директора", () => {
  it("плитки ведут в отчёт с периодом, динамика со знаком и «было», таблицы и «Внимание»", async () => {
    const f = world("director", { "GET /reports/dashboard": () => json(200, DASH) });
    open(<DirectorDashboard />);
    const link = await screen.findByRole("link", { name: /^Выручка/ });
    expect(link.getAttribute("href")).toMatch(/^\/reports\?report=revenue&date_from=\d{4}-\d{2}-\d{2}&date_to=\d{4}-\d{2}-\d{2}$/);
    expect(norm(link.textContent)).toContain("250 000,00 ₽");
    expect(within(link).getByText(/▲\s25,00\s%/)).toBeInTheDocument();
    expect(norm(link.textContent)).toContain("было 200 000,00 ₽");
    const load = screen.getByRole("link", { name: /^Загрузка постов/ });
    expect(within(load).getByText(/▼\s3,20\sп\.п\./)).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /^Конверсия записей/ })).getByText("—")).toBeInTheDocument();

    // директор с «Все точки»: location_id не передаётся
    expect(String(calls(f, "GET /reports/dashboard")[0][0])).not.toContain("location_id");

    const points = within(screen.getByRole("region", { name: "Сравнение точек" }));
    expect(points.getByText("Москва-1")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Топ услуг" })).getByText("Замена масла")).toBeInTheDocument();
    const attention = within(screen.getByRole("region", { name: "Внимание" }));
    expect(attention.getByRole("link", { name: "Заказ MSK1-000009" })).toHaveAttribute("href", "/orders/o9");
    expect(attention.getByRole("link", { name: /Фильтр масляный/ })).toBeInTheDocument();
  });

  it("ошибка сервера: баннер без внутренних деталей и «Повторить»", async () => {
    let fail = true;
    world("director", { "GET /reports/dashboard": () => (fail ? apiError(404, "not_found") : json(200, DASH)) });
    open(<DirectorDashboard />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Не удалось загрузить");
    expect(alert).not.toHaveTextContent("SQLSTATE");
    expect(alert).not.toHaveTextContent("SERVER TEXT");
    fail = false;
    await userEvent.setup().click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("link", { name: /^Выручка/ })).toBeInTheDocument();
  });

  it("пустой период: понятное сообщение", async () => {
    const empty: Dashboard = {
      ...DASH,
      kpis: { ...DASH.kpis, revenue: kpi("money", "0.00", "0.00", null), orders_closed: kpi("count", "0", "0", null) },
      revenue_series: DASH.revenue_series.map((p) => ({ ...p, total: "0.00" })),
    };
    world("director", { "GET /reports/dashboard": () => json(200, empty) });
    open(<DirectorDashboard />);
    expect(await screen.findByText("Нет данных за период")).toBeInTheDocument();
  });
});

/* ---------- D-02 отчёты ---------- */

describe("D-02 отчёты", () => {
  it("таблица с итогами, группировка уходит в запрос; «Прибыль» строится по целым месяцам", async () => {
    const f = world("director", {
      "GET /reports/revenue": () => json(200, REVENUE),
      "GET /reports/profit": () => json(200, { ...REVENUE, id: "profit", title: "Прибыль" }),
    });
    open(<ReportsPage />, "/reports?date_from=2026-11-05&date_to=2026-11-09");
    expect(await screen.findByRole("heading", { name: "Отчёты" })).toBeInTheDocument();
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText(/150\s000,00/)).toHaveLength(2); // строка + «Итого»
    expect(within(table).getByText("Итого")).toBeInTheDocument();
    const q = String(calls(f, "GET /reports/revenue")[0][0]);
    expect(q).toContain("date_from=2026-11-05");
    expect(q).toContain("group_by=location");
    expect(q).not.toContain("location_id");

    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText("Группировка"), "day");
    await waitFor(() => expect(calls(f, "GET /reports/revenue").some(([i]) => String(i).includes("group_by=day"))).toBe(true));

    await u.click(screen.getByRole("button", { name: "Прибыль" }));
    expect(await screen.findByText(/строится по целым месяцам/)).toBeInTheDocument();
    await waitFor(() => expect(calls(f, "GET /reports/profit")).toHaveLength(1));
    const pq = String(calls(f, "GET /reports/profit")[0][0]);
    expect(pq).toContain("date_from=2026-11-01");
    expect(pq).toContain("date_to=2026-11-30");
  });

  it("имя механика ведёт на его карточку по user_id; пометка об усечённых строках", async () => {
    world("director", {
      "GET /reports/revenue": () => json(200, { ...REVENUE, truncated: true }),
      "GET /reports/mechanics": () => json(200, MECHANICS_REPORT),
    });
    open(<ReportsPage />);
    expect(await screen.findByText("Показаны первые 500 строк")).toBeInTheDocument();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Механики" }));
    expect(await screen.findByRole("link", { name: "Пётр Механик" })).toHaveAttribute("href", "/mechanics/m1");
    expect(screen.queryByText("Показаны первые 500 строк")).toBeNull();
    expect(screen.getByLabelText("Отдел")).toBeInTheDocument();
  });

  it("пустой отчёт, экспорт XLSX через api(), ошибка 429 без технических деталей", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test-1"), revokeObjectURL: vi.fn() }));
    const downloaded: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloaded.push(this.download);
    });
    let limited = false;
    const f = world("director", {
      "GET /reports/revenue": () => json(200, { ...REVENUE, rows: [], totals: null, chart: null }),
      "GET /reports/revenue/export": () =>
        limited ? apiError(429, "rate_limited", {}, { "Retry-After": "30" }) : new Response(new Blob(["PK"]), { status: 200, headers: { "Content-Type": "application/octet-stream" } }),
    });
    open(<ReportsPage />, "/reports?date_from=2026-11-01&date_to=2026-11-09");
    expect(await screen.findByText("За выбранный период данных нет")).toBeInTheDocument();
    const u = userEvent.setup();

    await u.click(screen.getByRole("button", { name: "XLSX" }));
    await waitFor(() => expect(calls(f, "GET /reports/revenue/export")).toHaveLength(1));
    expect(String(calls(f, "GET /reports/revenue/export")[0][0])).toContain("format=xlsx");
    await waitFor(() => expect(downloaded).toEqual(["report-revenue-2026-11-01_2026-11-09.xlsx"]));

    limited = true;
    await u.click(screen.getByRole("button", { name: "CSV" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Слишком много попыток/);
    expect(alert).not.toHaveTextContent("SERVER TEXT");
  });

  it("ошибка 422 по периоду объяснена по-русски", async () => {
    world("director", { "GET /reports/revenue": () => apiError(422, "validation_error", { date_to: "bad" }) });
    open(<ReportsPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Конец периода не раньше начала, не более 366 суток");
    expect(alert).not.toHaveTextContent("SQLSTATE");
  });
});

/* ---------- D-03 зарплата ---------- */

describe("D-03 зарплата", () => {
  function payrollWorld(over: Record<string, Handler> = {}) {
    return world("director", {
      "GET /payroll": (r) => json(200, sheetOf(r.query.get("month"))),
      "GET /payroll/m1": () => json(200, PAYROLL_DETAIL),
      "GET /payroll/schemes": () => json(200, []),
      "GET /users": () => json(200, { items: [makeUser("mechanic", { id: "m1", full_name: "Пётр Механик" })], total: 1 }),
      ...over,
    });
  }

  it("ведомость: итоги, предупреждение о работах без схемы, раскрытие сотрудника", async () => {
    const f = payrollWorld();
    open(<PayrollPage />);
    expect(await screen.findByRole("heading", { name: "Зарплата" })).toBeInTheDocument();
    const toggle = await screen.findByRole("button", { name: "Пётр Механик" });
    expect(screen.getByRole("status")).toHaveTextContent("Работ без схемы: 2");
    expect(screen.getByText("Без схемы: 2")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getAllByText(/35\s500,00/)).toHaveLength(2); // строка + «Итого»
    expect(within(table).getAllByText(/−500,00/).length).toBeGreaterThan(0);
    expect(String(calls(f, "GET /payroll")[0][0])).toMatch(/month=\d{4}-\d{2}/);

    const u = userEvent.setup();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await u.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("link", { name: "MSK1-000001" })).toHaveAttribute("href", "/orders/o1");
    expect(screen.getByText("Без схемы")).toBeInTheDocument(); // работа без схемы помечена
  });

  it("предыдущий месяц запрашивает другую ведомость; пустой месяц", async () => {
    const f = payrollWorld({ "GET /payroll": (r) => json(200, { ...sheetOf(r.query.get("month")), rows: [] }) });
    open(<PayrollPage />);
    expect(await screen.findByText("За выбранный месяц начислений нет")).toBeInTheDocument();
    const first = new URL(String(calls(f, "GET /payroll")[0][0]), "http://x").searchParams.get("month")!;
    await userEvent.setup().click(screen.getByRole("button", { name: "Предыдущий месяц" }));
    await waitFor(() => expect(calls(f, "GET /payroll")).toHaveLength(2));
    expect(new URL(String(calls(f, "GET /payroll")[1][0]), "http://x").searchParams.get("month")).toBe(shiftMonth(first, -1));
  });

  it("премия или удержание: сумма со знаком уходит строкой-десятичной", async () => {
    const f = payrollWorld({
      "POST /payroll/adjustments": () => json(201, { id: "a1", user: MECH, month: "2026-11", amount: "-500.00", reason: "Штраф за опоздание", created_by: MECH, created_at: "2026-11-09T09:00:00Z" }),
    });
    open(<PayrollPage />);
    const u = userEvent.setup();
    await screen.findByRole("button", { name: "Пётр Механик" });
    await u.click(screen.getAllByRole("button", { name: "Премия / удержание" })[0]);
    const dlg = within(await screen.findByRole("dialog", { name: "Премия / удержание" }));
    await waitFor(() => expect(dlg.getByLabelText("Сотрудник")).toHaveValue("m1"));
    await u.type(dlg.getByLabelText(/^Сумма/), "−500");
    await u.type(dlg.getByLabelText("Причина"), "Штраф за опоздание");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(calls(f, "POST /payroll/adjustments")).toHaveLength(1));
    expect(bodyOf(f, "POST /payroll/adjustments")).toMatchObject({ user_id: "m1", amount: "-500.00", reason: "Штраф за опоздание" });
    expect(String(bodyOf(f, "POST /payroll/adjustments").month)).toMatch(/^\d{4}-\d{2}$/);
  });

  it("схема оплаты: 409 scheme_overlap объяснён в форме, внутренние детали не показываются", async () => {
    const f = payrollWorld({ "POST /payroll/schemes": () => apiError(409, "scheme_overlap") });
    open(<PayrollPage />);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Пётр Механик" }));
    await screen.findByRole("link", { name: "MSK1-000001" });
    const buttons = screen.getAllByRole("button", { name: "Схемы оплаты" });
    await u.click(buttons[buttons.length - 1]); // кнопка внутри раскрытой строки: сотрудник уже выбран
    const dlg = within(await screen.findByRole("dialog", { name: "Схема оплаты" }));
    await u.type(await dlg.findByLabelText(/^Процент от работ/), "40");
    await u.click(dlg.getByRole("button", { name: "Добавить схему" }));
    await waitFor(() => expect(calls(f, "POST /payroll/schemes")).toHaveLength(1));
    expect(bodyOf(f, "POST /payroll/schemes")).toMatchObject({ user_id: "m1", scheme_type: "percent_of_works", percent: "40.00", department: null });
    const msg = await dlg.findByText("Для этого сотрудника на выбранные даты уже действует схема");
    expect(msg).toBeInTheDocument();
    expect(dlg.queryByText(/SQLSTATE|SERVER TEXT/)).toBeNull();
  });

  it("процент вне диапазона не уходит на сервер", async () => {
    const f = payrollWorld();
    open(<PayrollPage />);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Пётр Механик" }));
    await screen.findByRole("link", { name: "MSK1-000001" });
    const buttons = screen.getAllByRole("button", { name: "Схемы оплаты" });
    await u.click(buttons[buttons.length - 1]);
    const dlg = within(await screen.findByRole("dialog", { name: "Схема оплаты" }));
    await u.type(await dlg.findByLabelText(/^Процент от работ/), "150");
    await u.click(dlg.getByRole("button", { name: "Добавить схему" }));
    expect(await dlg.findByText(/Процент: число от 0 до 100/)).toBeInTheDocument();
    expect(calls(f, "POST /payroll/schemes")).toHaveLength(0);
  });
});

/* ---------- M-07 заработок ---------- */

describe("M-07 заработок механика", () => {
  it("итог за месяц, ожидающие закрытия, премии, работы по дням; цен работ нет", async () => {
    const f = world("mechanic", { "GET /me/earnings": (r) => json(200, earningsOf(r.query.get("month"))) });
    open(<EarningsPage />);
    expect(await screen.findByRole("heading", { name: "Заработок" })).toBeInTheDocument();
    const total = within(await screen.findByRole("region", { name: "Итого за месяц" }));
    expect(total.getByText(/43\s500,00/)).toBeInTheDocument();
    expect(norm(screen.getByText(/Ожидают закрытия заказа/).textContent)).toContain("Ожидают закрытия заказа: 2 работы");
    expect(screen.getByText("Премия за качество")).toBeInTheDocument();
    // Тот же заказ может быть и в панели «Мои рабочие дни» — проверяем блок выполненных работ.
    const works = within(screen.getByRole("region", { name: "Выполненные работы" }));
    expect(works.getByRole("link", { name: "Заказ MSK1-000001" })).toHaveAttribute("href", "/orders/o1");
    expect(works.getByText("Замена масла")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Следующий месяц" })).toBeDisabled();

    const first = new URL(String(calls(f, "GET /me/earnings")[0][0]), "http://x").searchParams.get("month")!;
    await userEvent.setup().click(screen.getByRole("button", { name: "Предыдущий месяц" }));
    await waitFor(() => expect(calls(f, "GET /me/earnings")).toHaveLength(2));
    expect(new URL(String(calls(f, "GET /me/earnings")[1][0]), "http://x").searchParams.get("month")).toBe(shiftMonth(first, -1));
  });

  it("карта «Мои рабочие дни» загружает данные своего пользователя", async () => {
    const f = world("mechanic", { "GET /me/earnings": (r) => json(200, earningsOf(r.query.get("month"))) });
    open(<EarningsPage />);
    expect(await screen.findByRole("region", { name: "Мои рабочие дни" })).toBeInTheDocument();
    await waitFor(() => expect(calls(f, "GET /users/u-mechanic/activity-heatmap").length).toBeGreaterThan(0));
  });
});

/* ---------- MG-16 отчёт точки ---------- */

describe("MG-16 отчёт точки", () => {
  it("менеджер: показатели, выработка механиков со ссылкой, переключатель периода; расходов и прибыли нет", async () => {
    const f = world("manager", { "GET /reports/location-summary": () => json(200, SUMMARY) });
    open(<LocationReportPage />);
    expect(await screen.findByRole("heading", { name: "Отчёт точки" })).toBeInTheDocument();
    expect(await screen.findByText(/123\s456,00/)).toBeInTheDocument();
    expect(screen.getByText(/15\s432,00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Пётр Механик" })).toHaveAttribute("href", "/mechanics/m1");
    expect(norm(document.body.textContent)).not.toMatch(/Прибыль|Расход|Себестоимость|Зарплата/);

    const q = String(calls(f, "GET /reports/location-summary")[0][0]);
    expect(q).toContain("location_id=l1");
    expect(q).toContain("period=day");

    const u = userEvent.setup();
    expect(screen.getByRole("button", { name: "День" })).toHaveAttribute("aria-pressed", "true");
    await u.click(screen.getByRole("button", { name: "Неделя" }));
    await waitFor(() => expect(calls(f, "GET /reports/location-summary").some(([i]) => String(i).includes("period=week"))).toBe(true));
    expect(screen.getByRole("button", { name: "Неделя" })).toHaveAttribute("aria-pressed", "true");
  });

  it("механик без данных эффективности: тире", async () => {
    const s: LocationSummary = { ...SUMMARY, mechanics: [{ ...SUMMARY.mechanics[0], efficiency: null }] };
    world("manager", { "GET /reports/location-summary": () => json(200, s) });
    open(<LocationReportPage />);
    const row = (await screen.findByRole("link", { name: "Пётр Механик" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("директор без выбранной точки: location_id не передаётся", async () => {
    const f = world("director", { "GET /reports/location-summary": () => json(200, SUMMARY) });
    open(<LocationReportPage />);
    await screen.findByRole("link", { name: "Пётр Механик" });
    expect(String(calls(f, "GET /reports/location-summary")[0][0])).not.toContain("location_id");
  });
});

/* ---------- MG-17 карточка механика ---------- */

describe("MG-17 рабочие дни сотрудника", () => {
  const mechanic = makeUser("mechanic", { id: "m1", full_name: "Пётр Механик", telegram_linked: true });

  it("менеджер видит имя (из карты) и карту без запроса /users/{id}; зарплаты и учётных данных нет", async () => {
    // GET /users/{id} — только руководитель: менеджеру бэкенд отвечает 403.
    const f = world("manager", { "GET /users/m1": () => apiError(403, "forbidden") });
    open(<MechanicActivityPage />, "/mechanics/m1", "/mechanics/:id");
    expect(await screen.findByRole("heading", { name: "Пётр Механик" })).toBeInTheDocument();
    await waitFor(() => expect(cell("2026-11-04")).toBeTruthy());
    expect(calls(f, "GET /users/m1")).toHaveLength(0);
    expect(norm(document.body.textContent)).not.toMatch(/Оклад|Зарплата|Логин|Пароль|Ставка/);
  });

  it("руководитель дополнительно видит точки и Telegram", async () => {
    world("director", { "GET /users/m1": () => json(200, mechanic) });
    open(<MechanicActivityPage />, "/mechanics/m1", "/mechanics/:id");
    expect(await screen.findByRole("heading", { name: "Пётр Механик" })).toBeInTheDocument();
    expect(await screen.findByText("Telegram подключён")).toBeInTheDocument();
    expect(screen.getByText("Москва-1")).toBeInTheDocument();
  });

  it("чужой сотрудник (404 по карте или по карточке у руководителя) — экран «не найден»", async () => {
    world("manager", { "GET /users/m1/activity-heatmap": () => apiError(404, "not_found") });
    const r1 = open(<MechanicActivityPage />, "/mechanics/m1", "/mechanics/:id");
    expect(await screen.findByRole("heading", { name: "Сотрудник не найден" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Карта активности по дням" })).toBeNull();
    r1.unmount();

    world("director", { "GET /users/m1": () => apiError(404, "not_found") });
    open(<MechanicActivityPage />, "/mechanics/m1", "/mechanics/:id");
    expect(await screen.findByRole("heading", { name: "Сотрудник не найден" })).toBeInTheDocument();
  });
});

/* ---------- MG-01 «Сегодня» ---------- */

describe("MG-01 сводка дня", () => {
  it("показатели со ссылками, механики с текущей работой", async () => {
    world("manager", { "GET /dashboard/today": () => json(200, TODAY) });
    open(<TodaySummary />);
    expect(await screen.findByRole("heading", { name: "Сегодня" })).toBeInTheDocument();
    expect(screen.getByText(/15\s000,00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Просрочено/ })).toHaveAttribute("href", "/orders?overdue=true");
    expect(screen.getByRole("link", { name: "Низкий остаток: 3" })).toHaveAttribute("href", "/stock");
    expect(screen.getByRole("link", { name: "Пётр Механик" })).toHaveAttribute("href", "/mechanics/m1");
    expect(norm(document.body.textContent)).toContain("Замена масла · заказ MSK1-000001");
  });

  it("ошибка сводки: блок скрыт, без баннера и уведомлений", async () => {
    const f = world("manager", { "GET /dashboard/today": () => apiError(404, "not_found") });
    const { container } = open(<TodaySummary />);
    await waitFor(() => expect(calls(f, "GET /dashboard/today")).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Сегодня")).toBeNull();
    expect(container.textContent).toBe("");
  });
});

/* ---------- D-05 вкладка активности в карточке сотрудника ---------- */

describe("D-05 вкладка «Активность»", () => {
  const u1 = makeUser("mechanic", { id: "m1", full_name: "Пётр Механик" });

  it("?tab=activity открывает карту; «Данные» возвращают форму", async () => {
    world("director", { "GET /users/m1": () => json(200, u1) });
    open(<UserPage />, "/users/m1?tab=activity", "/users/:id");
    expect(await screen.findByRole("tab", { name: "Активность" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(cell("2026-11-04")).toBeTruthy());
    expect(screen.queryByLabelText("ФИО")).toBeNull();

    await userEvent.setup().click(screen.getByRole("tab", { name: "Данные" }));
    expect(await screen.findByLabelText("ФИО")).toHaveValue("Пётр Механик");
    expect(screen.getByRole("tab", { name: "Данные" })).toHaveAttribute("aria-selected", "true");
  });
});
