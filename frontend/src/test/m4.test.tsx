import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import {
  STEP,
  assignLanes,
  clampMove,
  clampResize,
  defaultDurationMinutes,
  gridRange,
  overlaps,
  snap,
  validateInterval,
  TIME_ERROR_TEXT,
} from "@/features/appointments/grid";
import {
  addDays,
  dateOfMs,
  hhmm,
  isDateStr,
  minuteOfDay,
  parseHm,
  safeZone,
  toZonedIso,
  weekDates,
  weekStart,
  zoneOffsetMin,
  zonedTimeToMs,
} from "@/features/appointments/time";
import { ERROR_MESSAGES } from "@/shared/api/errors";
import type { Appointment, AppointmentStatus, Client, ClientDetail, Post, Role, Service, User, Vehicle } from "@/shared/api/types";

import { type Handler, LOC1, LOC2, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

/* ---------- чистые функции ---------- */

describe("время в поясе точки", () => {
  it("Москва: ISO со смещением и обратно", () => {
    const ms = Date.parse("2026-11-10T07:00:00Z");
    expect(toZonedIso(ms, "Europe/Moscow")).toBe("2026-11-10T10:00:00+03:00");
    expect(zonedTimeToMs("2026-11-10", 10 * 60, "Europe/Moscow")).toBe(ms);
    expect(zoneOffsetMin(ms, "Europe/Moscow")).toBe(180);
  });

  it("смена суток: 21:30 UTC в Москве уже следующий день 00:30", () => {
    const ms = Date.parse("2026-11-10T21:30:00Z");
    expect(dateOfMs(ms, "Europe/Moscow")).toBe("2026-11-11");
    expect(minuteOfDay(ms, "Europe/Moscow")).toBe(30);
    expect(dateOfMs(ms, "UTC")).toBe("2026-11-10");
  });

  it("пояса с другим смещением: Владивосток +10, Калининград +2", () => {
    const ms = Date.parse("2026-11-10T07:00:00Z");
    expect(hhmm(minuteOfDay(ms, "Asia/Vladivostok"))).toBe("17:00");
    expect(hhmm(minuteOfDay(ms, "Europe/Kaliningrad"))).toBe("09:00");
    expect(toZonedIso(ms, "Asia/Vladivostok")).toBe("2026-11-10T17:00:00+10:00");
  });

  it("летнее время: смещение берётся на нужную дату", () => {
    expect(zonedTimeToMs("2026-07-01", 12 * 60, "America/New_York")).toBe(Date.parse("2026-07-01T16:00:00Z"));
    expect(zonedTimeToMs("2026-12-01", 12 * 60, "America/New_York")).toBe(Date.parse("2026-12-01T17:00:00Z"));
    // день перехода на летнее время (8 марта 2026): после 03:00 уже EDT
    expect(zonedTimeToMs("2026-03-08", 12 * 60, "America/New_York")).toBe(Date.parse("2026-03-08T16:00:00Z"));
    expect(zonedTimeToMs("2026-11-01", 12 * 60, "America/New_York")).toBe(Date.parse("2026-11-01T17:00:00Z"));
  });

  it("неизвестный пояс не роняет расчёты", () => {
    expect(safeZone("Nope/Zone")).toBe("UTC");
    expect(minuteOfDay(Date.parse("2026-11-10T07:00:00Z"), "Nope/Zone")).toBe(7 * 60);
  });

  it("даты: недели, границы месяца и високосный год", () => {
    expect(weekStart("2026-11-10")).toBe("2026-11-09");
    expect(weekStart("2026-11-15")).toBe("2026-11-09");
    expect(weekStart("2026-11-09")).toBe("2026-11-09");
    expect(weekDates("2026-11-10")).toHaveLength(7);
    expect(weekDates("2026-11-10")[6]).toBe("2026-11-15");
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
    expect(addDays("2027-01-01", -1)).toBe("2026-12-31");
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
    expect(isDateStr("2026-02-30")).toBe(false);
    expect(isDateStr("2026-11-10")).toBe(true);
    expect(isDateStr("10.11.2026")).toBe(false);
  });

  it("parseHm: HH:MM и HH:MM:SS, мусор → null", () => {
    expect(parseHm("09:00")).toBe(540);
    expect(parseHm("21:00:00")).toBe(1260);
    expect(parseHm("24:00")).toBeNull();
    expect(parseHm("9-00")).toBeNull();
    expect(parseHm("")).toBeNull();
    expect(hhmm(65)).toBe("01:05");
  });
});

describe("сетка календаря", () => {
  it("пересечение полуоткрытых интервалов: конец одной записи = начало другой — не конфликт", () => {
    expect(overlaps({ start: 600, end: 660 }, { start: 660, end: 720 })).toBe(false);
    expect(overlaps({ start: 660, end: 720 }, { start: 600, end: 660 })).toBe(false);
    expect(overlaps({ start: 600, end: 661 }, { start: 660, end: 720 })).toBe(true);
    expect(overlaps({ start: 600, end: 720 }, { start: 630, end: 660 })).toBe(true);
  });

  it("привязка к шагу 15 минут", () => {
    expect(STEP).toBe(15);
    expect(snap(607)).toBe(600);
    expect(snap(608)).toBe(615);
    expect(snap(61, 5, "floor")).toBe(60);
    expect(snap(61, 5, "ceil")).toBe(65);
  });

  const work = { start: 9 * 60, end: 21 * 60 };

  it("перенос: длительность сохраняется, шаг 15, границы рабочего диапазона", () => {
    const iv = { start: 600, end: 660 };
    expect(clampMove(iv, 30, work)).toEqual({ start: 630, end: 690 });
    expect(clampMove(iv, 7, work)).toEqual({ start: 600, end: 660 });
    expect(clampMove(iv, 8, work)).toEqual({ start: 615, end: 675 });
    expect(clampMove(iv, -1000, work)).toEqual({ start: 540, end: 600 });
    expect(clampMove(iv, 1000, work)).toEqual({ start: 1200, end: 1260 });
  });

  it("растягивание: минимум 15 минут, максимум 12 часов и конец диапазона", () => {
    const iv = { start: 600, end: 660 };
    expect(clampResize(iv, 30, work)).toEqual({ start: 600, end: 690 });
    expect(clampResize(iv, -1000, work)).toEqual({ start: 600, end: 615 });
    expect(clampResize(iv, 1000, work)).toEqual({ start: 600, end: 1260 });
    expect(clampResize({ start: 0, end: 60 }, 5000, { start: 0, end: 1440 })).toEqual({ start: 0, end: 720 });
  });

  it("раскладка по дорожкам: смежные записи не делят ширину, пересекающиеся — делят", () => {
    const a = { start: 600, end: 660 };
    const b = { start: 660, end: 720 };
    expect(assignLanes([a, b]).map((x) => [x.lane, x.lanes])).toEqual([[0, 1], [0, 1]]);
    const c = { start: 630, end: 700 };
    const out = assignLanes([a, b, c]);
    expect(out.find((x) => x.item === c)).toMatchObject({ lane: 1, lanes: 2 });
    expect(out.find((x) => x.item === a)).toMatchObject({ lane: 0, lanes: 2 });
    // освободившаяся дорожка используется повторно
    const d = { start: 700, end: 720 };
    expect(assignLanes([a, c, d]).find((x) => x.item === d)).toMatchObject({ lane: 0 });
  });

  it("длительность по умолчанию: сумма услуг (кратно 5), иначе 60", () => {
    expect(defaultDurationMinutes([])).toBe(60);
    expect(defaultDurationMinutes([{ duration_minutes: 30 }, { duration_minutes: 50 }])).toBe(80);
    expect(defaultDurationMinutes([{ duration_minutes: 62 }])).toBe(65);
    expect(defaultDurationMinutes([{ duration_minutes: 0 }])).toBe(60);
    expect(defaultDurationMinutes([{ duration_minutes: 2000 }])).toBe(720);
  });

  it("диапазон сетки расширяется записью вне рабочих часов", () => {
    expect(gridRange(work, [])).toEqual(work);
    expect(gridRange(work, [{ start: 8 * 60 + 30, end: 9 * 60 + 30 }])).toEqual({ start: 8 * 60, end: 21 * 60 });
    expect(gridRange(work, [{ start: 20 * 60, end: 21 * 60 + 30 }])).toEqual({ start: 9 * 60, end: 22 * 60 });
  });

  it("проверка интервала зеркалит контракт", () => {
    expect(validateInterval({ start: 600, end: 660 }, work)).toBeNull();
    expect(validateInterval({ start: 600, end: 600 }, work)).toBe("order");
    expect(validateInterval({ start: 660, end: 600 }, work)).toBe("order");
    expect(validateInterval({ start: 600, end: 617 }, work)).toBe("step");
    expect(validateInterval({ start: 600, end: 610 }, work)).toBe("too_short");
    expect(validateInterval({ start: 0, end: 13 * 60 }, { start: 0, end: 1440 })).toBe("too_long");
    expect(validateInterval({ start: 0, end: 12 * 60 }, { start: 0, end: 1440 })).toBeNull();
    // нерабочее время
    expect(validateInterval({ start: 8 * 60, end: 9 * 60 }, work)).toBe("work_hours");
    expect(validateInterval({ start: 20 * 60 + 30, end: 21 * 60 + 30 }, work)).toBe("work_hours");
    // ровно до конца рабочего дня — можно
    expect(validateInterval({ start: 20 * 60, end: 21 * 60 }, work)).toBeNull();
    expect(Object.keys(TIME_ERROR_TEXT)).toHaveLength(5);
  });
});

/* ---------- интеграция ---------- */

const POSTS: Post[] = [
  { id: "po1", location_id: "l1", name: "Пост 1", post_type: "lift", department: "service", sort_order: 0, is_active: true },
  { id: "po2", location_id: "l1", name: "Пост 2", post_type: "lift", department: "service", sort_order: 1, is_active: true },
  { id: "po3", location_id: "l1", name: "Бокс детейлинга", post_type: "detailing_box", department: "detailing", sort_order: 2, is_active: true },
  { id: "po4", location_id: "l1", name: "Закрытый пост", post_type: "lift", department: "service", sort_order: 3, is_active: false },
];

const SERVICES: Service[] = [
  { id: "s1", category_id: "c1", code: "TO-1", name: "Замена масла", description: null, department: "service", unit: "pcs", base_price: "1500.00", norm_hours: "1.00", duration_minutes: 60, is_active: true, price: "1500.00" },
  { id: "s2", category_id: "c1", code: "DG-1", name: "Диагностика", description: null, department: "service", unit: "pcs", base_price: "900.00", norm_hours: "1.50", duration_minutes: 90, is_active: true, price: "900.00" },
  { id: "s3", category_id: "c2", code: "PL-1", name: "Полировка кузова", description: null, department: "detailing", unit: "pcs", base_price: "9000.00", norm_hours: "4.00", duration_minutes: 240, is_active: true, price: "9000.00" },
];

const VEH: Vehicle = {
  id: "v1",
  client_id: "c1",
  make: "Kia",
  model: "Rio",
  year: 2018,
  vin: null,
  plate_number: "А123ВС777",
  color: null,
  mileage: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  archived_at: null,
};

const CLIENT: Client = {
  id: "c1",
  client_type: "person",
  full_name: "Иван Петров",
  company_name: null,
  inn: null,
  phone: "+79991234567",
  phone_extra: null,
  email: null,
  source: null,
  discount_percent: 0,
  notes: null,
  vehicles_count: 1,
  created_at: "2026-01-01T00:00:00Z",
  archived_at: null,
};

function appt(o: Partial<Appointment> = {}): Appointment {
  return {
    id: "a1",
    location_id: "l1",
    client_id: "c1",
    vehicle_id: "v1",
    post_id: "po1",
    department: "service",
    start_at: "2026-11-10T10:00:00+03:00",
    end_at: "2026-11-10T11:00:00+03:00",
    status: "scheduled",
    comment: null,
    service_ids: ["s1"],
    services: [{ id: "s1", name: "Замена масла" }],
    client: { id: "c1", full_name: "Иван Петров", phone: "+79991234567" },
    vehicle: { id: "v1", make: "Kia", model: "Rio", plate_number: "А123ВС777" },
    work_order_id: null,
    created_by: "u-manager",
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...o,
  };
}

const page = <T,>(items: T[]) => json(200, { items, total: items.length });

function world(opts: { user?: User; appts?: Appointment[]; over?: Record<string, Handler>; locs?: typeof LOC1[] } = {}) {
  const user = opts.user ?? makeUser("manager");
  const state = { appts: [...(opts.appts ?? [appt()])] };
  const f = mockApi({
    "POST /auth/refresh": () => json(200, session(user)),
    "GET /locations": () => json(200, opts.locs ?? [LOC1]),
    "GET /locations/l1/posts": () => json(200, POSTS),
    "GET /appointments": (r) => {
      const d = r.query.get("department");
      return json(200, state.appts.filter((a) => !d || a.department === d));
    },
    "GET /services": () => page(SERVICES),
    "GET /clients": () => page([CLIENT]),
    "GET /clients/c1": () => json(200, { ...CLIENT, vehicles: [VEH] } satisfies ClientDetail),
    ...opts.over,
  });
  return { f, state };
}

function open(path = "/calendar") {
  window.history.pushState({}, "", path);
  return render(<App />);
}

const q = (call: unknown[]) => new URL(String(call[0]), "http://x").searchParams;
const card = (id = "a1") => document.querySelector<HTMLElement>(`[data-appointment="${id}"]`);
const slot = (post: string, sub: string, time: string) => `Создать запись: ${post}, ${sub}, ${time}`;
const bodyOf = (f: ReturnType<typeof mockApi>, key: string, i = 0) => JSON.parse(String(calls(f, key)[i][1]?.body)) as Record<string, unknown>;

class PointerEventPolyfill extends MouseEvent {
  pointerType: string;
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerType?: string; pointerId?: number } = {}) {
    super(type, init);
    this.pointerType = init.pointerType ?? "mouse";
    this.pointerId = init.pointerId ?? 1;
  }
}
const ptr = (type: string, x: number, y: number) =>
  new PointerEventPolyfill(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, pointerType: "mouse" });

/** Колонки сетки получают координаты по порядку: 200 пикселей на колонку. */
function stubColumnRects(order: string[]) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    const i = order.indexOf(this.getAttribute("data-col") ?? "");
    const left = i < 0 ? 0 : i * 200;
    const width = i < 0 ? 0 : 200;
    return { left, right: left + width, top: 0, bottom: 1000, width, height: 1000, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
  });
}

function stubMatchMedia(mobile: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: mobile && query.includes("max-width: 767px"),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

beforeEach(() => {
  // 10 ноября 2026, 12:00 по Москве
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-10T09:00:00Z"));
  (document.defaultView as unknown as { PointerEvent: unknown }).PointerEvent = PointerEventPolyfill;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "matchMedia");
});

describe("календарь: отображение", () => {
  it("колонки — активные посты, запись на своём месте, запрос с точкой и датой", async () => {
    const { f } = world();
    open();
    expect(await screen.findByText("Пост 1")).toBeInTheDocument();
    expect(screen.getByText("Пост 2")).toBeInTheDocument();
    expect(screen.getByText("Бокс детейлинга")).toBeInTheDocument();
    expect(screen.queryByText("Закрытый пост")).toBeNull();
    await waitFor(() => expect(card()).not.toBeNull());
    const c = card() as HTMLElement;
    expect(c).toHaveAttribute("aria-label", "10:00–11:00, А123ВС777, Иван Петров, Запланирована");
    // 10:00 при начале сетки в 09:00: час = 60 мин × 1.6 пикселя
    expect(c.style.top).toBe("96px");
    expect(c.style.height).toBe("96px");
    expect(c).toHaveTextContent("Замена масла");
    const query = q(calls(f, "GET /appointments")[0]);
    expect(query.get("location_id")).toBe("l1");
    expect(query.get("date_from")).toBe("2026-11-10");
    expect(query.get("date_to")).toBe("2026-11-10");
    expect(query.get("department")).toBeNull();
    // сетка ограничена рабочими часами: нет слота 08:45 и есть 20:45
    expect(screen.queryByLabelText(slot("Пост 1", "Сервис", "08:45"))).toBeNull();
    expect(screen.getByLabelText(slot("Пост 1", "Сервис", "20:45"))).toBeInTheDocument();
  });

  it("линия текущего времени только в сегодняшнем дне", async () => {
    world();
    open();
    await screen.findByText("Пост 1");
    const lines = await screen.findAllByTestId("now-line");
    expect(lines).toHaveLength(3);
    // 12:00 при начале сетки 09:00: 180 мин × 1.6
    expect(lines[0].style.top).toBe("288px");
    await userEvent.setup().click(screen.getByRole("button", { name: "Следующий день" }));
    await waitFor(() => expect(screen.queryAllByTestId("now-line")).toHaveLength(0));
    await userEvent.setup().click(screen.getByRole("button", { name: "Сегодня" }));
    expect(await screen.findAllByTestId("now-line")).toHaveLength(3);
  });

  it("навигация по дням: запросы с новой датой", async () => {
    const { f } = world();
    open();
    await screen.findByText("Пост 1");
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Предыдущий день" }));
    await waitFor(() => expect(calls(f, "GET /appointments").some((c) => q(c).get("date_from") === "2026-11-09")).toBe(true));
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("9 ноября");
    await u.click(screen.getByRole("button", { name: "Сегодня" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("10 ноября"));
  });

  it("режим «Неделя»: диапазон понедельник–воскресенье, колонки — дни выбранного поста", async () => {
    const { f } = world();
    open();
    await screen.findByText("Пост 1");
    const u = userEvent.setup();
    await u.click(within(screen.getByRole("group", { name: "Режим" })).getByRole("button", { name: "Неделя" }));
    await waitFor(() => expect(calls(f, "GET /appointments").some((c) => q(c).get("date_from") === "2026-11-09" && q(c).get("date_to") === "2026-11-15")).toBe(true));
    await waitFor(() => expect(document.querySelectorAll("[data-col]")).toHaveLength(7));
    expect(document.querySelector('[data-col="2026-11-10"] [data-appointment="a1"]')).not.toBeNull();
    expect(screen.getByLabelText("Пост недели")).toHaveValue("po1");
  });

  it("фильтр по отделу: запрос с department, лишние посты и записи скрыты", async () => {
    const det = appt({ id: "a2", post_id: "po3", department: "detailing", services: [], service_ids: [], vehicle: { id: "v2", make: "BMW", model: "X5", plate_number: "Е555КХ99" } });
    const { f } = world({ appts: [appt(), det] });
    open();
    await screen.findByText("Пост 1");
    await waitFor(() => expect(card("a2")).not.toBeNull());
    const u = userEvent.setup();
    await u.click(within(screen.getByRole("group", { name: "Отдел" })).getByRole("button", { name: "Детейлинг" }));
    await waitFor(() => expect(calls(f, "GET /appointments").some((c) => q(c).get("department") === "detailing")).toBe(true));
    await waitFor(() => expect(screen.queryByText("Пост 1")).toBeNull());
    expect(screen.getByText("Бокс детейлинга")).toBeInTheDocument();
    await waitFor(() => expect(card("a1")).toBeNull());
    expect(card("a2")).not.toBeNull();
    await u.click(within(screen.getByRole("group", { name: "Отдел" })).getByRole("button", { name: "Все" }));
    expect(await screen.findByText("Пост 1")).toBeInTheDocument();
  });

  it("статусы различимы не только цветом: подпись в имени, зачёркивание для «не приехал» и «отменена»", async () => {
    world({
      appts: [
        appt({ id: "a1", status: "confirmed" }),
        appt({ id: "a2", status: "no_show", post_id: "po2" }),
        appt({ id: "a3", status: "cancelled", post_id: "po2", start_at: "2026-11-10T13:00:00+03:00", end_at: "2026-11-10T14:00:00+03:00" }),
        appt({ id: "a4", status: "arrived", post_id: "po1", start_at: "2026-11-10T15:00:00+03:00", end_at: "2026-11-10T16:00:00+03:00" }),
      ],
    });
    open();
    await waitFor(() => expect(card("a4")).not.toBeNull());
    expect(card("a1")?.getAttribute("aria-label")).toContain("Подтверждена");
    expect(card("a2")?.getAttribute("aria-label")).toContain("Не приехал");
    expect(card("a3")?.getAttribute("aria-label")).toContain("Отменена");
    expect(card("a4")?.getAttribute("aria-label")).toContain("Клиент приехал");
    expect(card("a2")?.querySelector(".line-through")).not.toBeNull();
    expect(card("a3")?.querySelector(".line-through")).not.toBeNull();
    expect(card("a1")?.querySelector(".line-through")).toBeNull();
    // записи в конечных статусах нельзя тянуть
    expect(card("a2")?.querySelector("[data-resize]")).toBeNull();
    expect(card("a1")?.querySelector("[data-resize]")).not.toBeNull();
  });
});

describe("календарь: доступ", () => {
  it("механик: нет пункта меню, по прямому URL «Нет доступа», запросов записей нет", async () => {
    const { f } = world({ user: makeUser("mechanic") });
    open();
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Календарь" })).toBeNull();
    expect(calls(f, "GET /appointments")).toHaveLength(0);
  });

  it.each<Role>(["manager", "director"])("%s видит пункт меню «Календарь»", async (role) => {
    world({ user: makeUser(role) });
    open("/");
    expect((await screen.findAllByRole("link", { name: "Календарь" })).length).toBeGreaterThan(0);
  });

  it("несколько точек: выбор точки меняет запрос", async () => {
    const { f } = world({
      user: makeUser("director", { location_ids: ["l1", "l2"] }),
      locs: [LOC1, LOC2],
      over: { "GET /locations/l2/posts": () => json(200, []) },
    });
    open();
    const sel = await screen.findByLabelText("Точка календаря");
    await waitFor(() => expect(calls(f, "GET /appointments").length).toBeGreaterThan(0));
    await userEvent.setup().selectOptions(sel, "l2");
    await waitFor(() => expect(calls(f, "GET /appointments").some((c) => q(c).get("location_id") === "l2")).toBe(true));
    expect(await screen.findByText("Для этой точки нет активных постов")).toBeInTheDocument();
  });
});

describe("создание записи", () => {
  async function openSlot(u: ReturnType<typeof userEvent.setup>, time = "10:15") {
    await screen.findByText("Пост 1");
    await u.click(await screen.findByLabelText(slot("Пост 1", "Сервис", time)));
    return within(await screen.findByRole("dialog", { name: "Новая запись" }));
  }

  async function pickClient(u: ReturnType<typeof userEvent.setup>, dlg: ReturnType<typeof within>) {
    await u.type(dlg.getByLabelText("Поиск клиента"), "Пет");
    await u.click(await dlg.findByRole("button", { name: /Иван Петров/ }));
    await u.selectOptions(await dlg.findByLabelText("Автомобиль"), "v1");
  }

  it("у клиента одно авто — оно подставляется сразу после выбора клиента", async () => {
    world({});
    open();
    const u = userEvent.setup();
    const dlg = await openSlot(u);
    await u.type(dlg.getByLabelText("Поиск клиента"), "Пет");
    await u.click(await dlg.findByRole("button", { name: /Иван Петров/ }));
    await waitFor(() => expect(dlg.getByLabelText("Автомобиль")).toHaveValue("v1"));
  });

  it("клик по пустому слоту открывает форму с постом и временем; создание отправляет ISO с поясом точки", async () => {
    const { f, state } = world({
      over: {
        "POST /appointments": (r) => {
          const b = r.body as Record<string, string>;
          const created = appt({ id: "a9", start_at: b.start_at, end_at: b.end_at, post_id: b.post_id, status: "scheduled", services: [{ id: "s2", name: "Диагностика" }], service_ids: ["s2"] });
          state.appts.push(created);
          return json(201, created);
        },
      },
    });
    open();
    const u = userEvent.setup();
    const dlg = await openSlot(u);
    expect(dlg.getByLabelText("Пост")).toHaveValue("po1");
    expect(dlg.getByLabelText("Отдел")).toHaveValue("service");
    expect(dlg.getByLabelText("Дата")).toHaveValue("2026-11-10");
    expect(dlg.getByLabelText("Начало")).toHaveValue("10:15");
    expect(dlg.getByLabelText("Окончание")).toHaveValue("11:15");

    await pickClient(u, dlg);
    // запрос поиска с параметром search
    expect(calls(f, "GET /clients").some((c) => q(c).get("search") === "Пет")).toBe(true);
    // услуга 90 минут меняет длительность по умолчанию
    await u.click(await dlg.findByRole("checkbox", { name: /Диагностика/ }));
    expect(dlg.getByLabelText("Окончание")).toHaveValue("11:45");
    // услуги другого отдела не предлагаются
    expect(dlg.queryByRole("checkbox", { name: /Полировка/ })).toBeNull();
    await u.type(dlg.getByLabelText("Комментарий"), "  Стук спереди ");
    await u.click(dlg.getByRole("button", { name: "Создать запись" }));

    await waitFor(() => expect(calls(f, "POST /appointments")).toHaveLength(1));
    expect(bodyOf(f, "POST /appointments")).toEqual({
      location_id: "l1",
      client_id: "c1",
      vehicle_id: "v1",
      department: "service",
      post_id: "po1",
      start_at: "2026-11-10T10:15:00+03:00",
      end_at: "2026-11-10T11:45:00+03:00",
      service_ids: ["s2"],
      comment: "Стук спереди",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(card("a9")).not.toBeNull());
  });

  it("быстрое создание клиента и авто: POST /clients, затем POST /clients/{id}/vehicles, затем запись", async () => {
    const newClient: Client = { ...CLIENT, id: "c9", full_name: "Пётр Новый", phone: "+79990001122", vehicles_count: 0 };
    const newVeh: Vehicle = { ...VEH, id: "v9", client_id: "c9", make: "Lada", model: "Vesta", plate_number: "К777КК77" };
    const { f } = world({
      over: {
        "POST /clients": () => json(201, newClient),
        "GET /clients/c9": () => json(200, { ...newClient, vehicles: [] } satisfies ClientDetail),
        "POST /clients/c9/vehicles": () => json(201, newVeh),
        "POST /appointments": (r) => json(201, appt({ id: "a9", ...(r.body as object) })),
      },
    });
    open();
    const u = userEvent.setup();
    const dlg = await openSlot(u);
    await u.click(dlg.getByRole("button", { name: "+ Новый клиент" }));
    // пустая форма: ошибки, запросов нет
    await u.click(dlg.getByRole("button", { name: "Создать клиента и авто" }));
    expect((await dlg.findAllByText("Обязательное поле")).length).toBeGreaterThan(0);
    expect(calls(f, "POST /clients")).toHaveLength(0);

    await u.type(dlg.getByLabelText(/^ФИО/), "Пётр Новый");
    await u.type(dlg.getByLabelText(/^Телефон/), "9990001122");
    await u.type(dlg.getByLabelText(/^Марка/), "Lada");
    await u.type(dlg.getByLabelText(/^Модель/), "Vesta");
    await u.type(dlg.getByLabelText("Госномер"), "к777кк77");
    await u.click(dlg.getByRole("button", { name: "Создать клиента и авто" }));

    await waitFor(() => expect(calls(f, "POST /clients/c9/vehicles")).toHaveLength(1));
    expect(bodyOf(f, "POST /clients")).toMatchObject({ full_name: "Пётр Новый", phone: "+79990001122", client_type: "person" });
    expect(bodyOf(f, "POST /clients/c9/vehicles")).toMatchObject({ make: "Lada", model: "Vesta", plate_number: "К777КК77" });
    expect(await dlg.findByText("Пётр Новый")).toBeInTheDocument();
    expect(dlg.getByLabelText(/^Автомобиль/)).toHaveValue("v9");

    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    await waitFor(() => expect(calls(f, "POST /appointments")).toHaveLength(1));
    expect(bodyOf(f, "POST /appointments")).toMatchObject({ client_id: "c9", vehicle_id: "v9" });
  });

  it("клиентская валидация: клиент не выбран, окончание раньше начала, нерабочее время, шаг 5 минут", async () => {
    const { f } = world();
    open();
    const u = userEvent.setup();
    const dlg = await openSlot(u);
    const start = dlg.getByLabelText("Начало");
    const end = dlg.getByLabelText("Окончание");

    fireEvent.change(end, { target: { value: "10:00" } });
    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    expect(await dlg.findByText("Выберите клиента")).toBeInTheDocument();
    expect(dlg.getByText(TIME_ERROR_TEXT.order)).toBeInTheDocument();

    fireEvent.change(end, { target: { value: "10:17" } });
    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    expect(await dlg.findByText(TIME_ERROR_TEXT.step)).toBeInTheDocument();

    fireEvent.change(end, { target: { value: "10:20" } });
    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    expect(await dlg.findByText(TIME_ERROR_TEXT.too_short)).toBeInTheDocument();

    fireEvent.change(start, { target: { value: "08:00" } });
    fireEvent.change(end, { target: { value: "09:00" } });
    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    expect(await dlg.findByText(TIME_ERROR_TEXT.work_hours)).toBeInTheDocument();
    expect(calls(f, "POST /appointments")).toHaveLength(0);
  });

  it("ошибки сервера: поле из словаря и без серверного текста; 409 post_busy с интервалом конфликта", async () => {
    let n = 0;
    const { f } = world({
      over: {
        "POST /appointments": () => {
          n += 1;
          if (n === 1) return apiError(422, "validation_error", { vehicle_id: "invalid" });
          if (n === 2) return json(409, { error: { code: "post_busy", message: "SERVER TEXT SQLSTATE", fields: {}, details: { conflict_id: "x", start_at: "2026-11-10T10:00:00+03:00", end_at: "2026-11-10T11:00:00+03:00" } } });
          return apiError(422, "outside_working_hours");
        },
      },
    });
    open();
    const u = userEvent.setup();
    const dlg = await openSlot(u);
    await pickClient(u, dlg);

    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    await waitFor(() => expect(dlg.getByLabelText(/^Автомобиль/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.queryByText(/SERVER TEXT/)).toBeNull();

    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    const alert = await dlg.findByText(/Пост занят/);
    expect(alert).toHaveTextContent("Занято с 10:00 до 11:00");
    expect(screen.queryByText(/SERVER TEXT/)).toBeNull();

    await u.click(dlg.getByRole("button", { name: "Создать запись" }));
    expect(await dlg.findByText(ERROR_MESSAGES.outside_working_hours)).toBeInTheDocument();
    expect(dlg.getByLabelText("Начало")).toHaveValue("10:15");
    expect(calls(f, "POST /appointments")).toHaveLength(3);
  });

  it("Escape закрывает форму без запросов", async () => {
    const { f } = world();
    open();
    const u = userEvent.setup();
    await openSlot(u);
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls(f, "POST /appointments")).toHaveLength(0);
  });
});

describe("перенос и изменение длительности", () => {
  async function ready() {
    await screen.findByText("Пост 1");
    await waitFor(() => expect(card()).not.toBeNull());
    stubColumnRects(["po1", "po2", "po3"]);
  }

  it("перетаскивание на другой пост и время: PATCH с post_id и ISO, шаг 15 минут", async () => {
    const { f, state } = world({
      over: {
        "PATCH /appointments/a1": (r) => {
          const b = r.body as Record<string, string>;
          state.appts[0] = appt({ post_id: b.post_id, start_at: b.start_at, end_at: b.end_at });
          return json(200, state.appts[0]);
        },
      },
    });
    open();
    await ready();
    const c = card() as HTMLElement;
    fireEvent(c, ptr("pointerdown", 50, 100));
    // 48 пикселей вниз = 30 минут, вправо — во вторую колонку
    act(() => {
      window.dispatchEvent(ptr("pointermove", 250, 148));
    });
    expect(card()).toHaveAttribute("aria-label", expect.stringContaining("10:30–11:30"));
    act(() => {
      window.dispatchEvent(ptr("pointerup", 250, 148));
    });
    await waitFor(() => expect(calls(f, "PATCH /appointments/a1")).toHaveLength(1));
    expect(bodyOf(f, "PATCH /appointments/a1")).toEqual({
      post_id: "po2",
      start_at: "2026-11-10T10:30:00+03:00",
      end_at: "2026-11-10T11:30:00+03:00",
    });
    await waitFor(() => expect(document.querySelector('[data-col="po2"] [data-appointment="a1"]')).not.toBeNull());
    // окно деталей не открылось: после перетаскивания клик подавляется
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("перетаскивание на пост другого отдела не переносит запись", async () => {
    const { f } = world();
    open();
    await ready();
    fireEvent(card() as HTMLElement, ptr("pointerdown", 50, 100));
    act(() => {
      window.dispatchEvent(ptr("pointermove", 450, 100));
      window.dispatchEvent(ptr("pointerup", 450, 100));
    });
    // колонка детейлинга игнорируется, время и пост не изменились: запроса нет
    await new Promise((r) => setTimeout(r, 30));
    expect(calls(f, "PATCH /appointments/a1")).toHaveLength(0);
    expect(document.querySelector('[data-col="po1"] [data-appointment="a1"]')).not.toBeNull();
  });

  it("тянем нижний край: меняется только окончание", async () => {
    const { f, state } = world({
      over: {
        "PATCH /appointments/a1": (r) => {
          const b = r.body as Record<string, string>;
          state.appts[0] = appt({ start_at: b.start_at, end_at: b.end_at });
          return json(200, state.appts[0]);
        },
      },
    });
    open();
    await ready();
    const handle = document.querySelector('[data-resize="a1"]') as HTMLElement;
    fireEvent(handle, ptr("pointerdown", 50, 190));
    act(() => {
      window.dispatchEvent(ptr("pointermove", 50, 214));
      window.dispatchEvent(ptr("pointerup", 50, 214));
    });
    await waitFor(() => expect(calls(f, "PATCH /appointments/a1")).toHaveLength(1));
    expect(bodyOf(f, "PATCH /appointments/a1")).toEqual({
      post_id: "po1",
      start_at: "2026-11-10T10:00:00+03:00",
      end_at: "2026-11-10T11:15:00+03:00",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("409 post_busy: карточка возвращается на место, показано «Пост занят»", async () => {
    const { f } = world({ over: { "PATCH /appointments/a1": () => apiError(409, "post_busy") } });
    open();
    await ready();
    fireEvent(card() as HTMLElement, ptr("pointerdown", 50, 100));
    act(() => {
      window.dispatchEvent(ptr("pointermove", 250, 148));
      window.dispatchEvent(ptr("pointerup", 250, 148));
    });
    await waitFor(() => expect(calls(f, "PATCH /appointments/a1")).toHaveLength(1));
    expect(await screen.findByText(ERROR_MESSAGES.post_busy)).toBeInTheDocument();
    expect(ERROR_MESSAGES.post_busy).toBe("Пост занят");
    await waitFor(() => expect(document.querySelector('[data-col="po1"] [data-appointment="a1"]')).not.toBeNull());
    expect(card()).toHaveAttribute("aria-label", expect.stringContaining("10:00–11:00"));
    expect(screen.queryByText(/SERVER TEXT/)).toBeNull();
  });

  it("запись в конечном статусе и касание пальцем не перетаскиваются", async () => {
    const { f } = world({ appts: [appt({ status: "arrived" })] });
    open();
    await ready();
    fireEvent(card() as HTMLElement, ptr("pointerdown", 50, 100));
    act(() => {
      window.dispatchEvent(ptr("pointermove", 250, 148));
      window.dispatchEvent(ptr("pointerup", 250, 148));
    });
    await new Promise((r) => setTimeout(r, 30));
    expect(calls(f, "PATCH /appointments/a1")).toHaveLength(0);
  });
});

describe("карточка записи и статусы", () => {
  it("клавиатура: карточка фокусируется, Enter открывает детали со ссылками на клиента и авто", async () => {
    world();
    open();
    await waitFor(() => expect(card()).not.toBeNull());
    const c = card() as HTMLElement;
    expect(c).toHaveAttribute("tabindex", "0");
    c.focus();
    await userEvent.setup().keyboard("{Enter}");
    const dlg = within(await screen.findByRole("dialog", { name: "Запись" }));
    expect(dlg.getByRole("link", { name: "Иван Петров" })).toHaveAttribute("href", "/clients/c1");
    expect(dlg.getByRole("link", { name: "А123ВС777" })).toHaveAttribute("href", "/vehicles/v1");
    expect(dlg.getByText("Пост 1")).toBeInTheDocument();
    // для запланированной записи доступны все четыре действия и правка
    for (const name of ["Подтвердить", "Клиент приехал", "Не приехал", "Отменить", "Редактировать"]) {
      expect(dlg.getByRole("button", { name })).toBeInTheDocument();
    }
    await userEvent.setup().keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("«Подтвердить» отправляет статус confirmed и закрывает окно", async () => {
    const { f, state } = world({
      over: {
        "POST /appointments/a1/status": (r) => {
          state.appts[0] = appt({ status: (r.body as { status: AppointmentStatus }).status });
          return json(200, state.appts[0]);
        },
      },
    });
    open();
    await waitFor(() => expect(card()).not.toBeNull());
    const u = userEvent.setup();
    await u.click(card() as HTMLElement);
    await u.click(within(await screen.findByRole("dialog", { name: "Запись" })).getByRole("button", { name: "Подтвердить" }));
    await waitFor(() => expect(calls(f, "POST /appointments/a1/status")).toHaveLength(1));
    expect(bodyOf(f, "POST /appointments/a1/status")).toEqual({ status: "confirmed" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(card()?.getAttribute("aria-label")).toContain("Подтверждена"));
    // из «подтверждена» уже нельзя вернуться в «подтвердить»
    await u.click(card() as HTMLElement);
    const dlg = within(await screen.findByRole("dialog", { name: "Запись" }));
    expect(dlg.queryByRole("button", { name: "Подтвердить" })).toBeNull();
    expect(dlg.getByRole("button", { name: "Клиент приехал" })).toBeInTheDocument();
  });

  it("«Отменить» и «Не приехал» требуют подтверждения; «Назад» ничего не отправляет", async () => {
    const { f } = world({ over: { "POST /appointments/a1/status": () => json(200, appt({ status: "cancelled" })) } });
    open();
    await waitFor(() => expect(card()).not.toBeNull());
    const u = userEvent.setup();
    await u.click(card() as HTMLElement);
    const dlg = within(await screen.findByRole("dialog", { name: "Запись" }));
    await u.click(dlg.getByRole("button", { name: "Отменить" }));
    expect(dlg.getByText(/Отменить запись\?/)).toBeInTheDocument();
    await u.click(dlg.getByRole("button", { name: "Назад" }));
    expect(calls(f, "POST /appointments/a1/status")).toHaveLength(0);
    await u.click(dlg.getByRole("button", { name: "Отменить" }));
    await u.click(dlg.getByRole("button", { name: "Да, отменить" }));
    await waitFor(() => expect(calls(f, "POST /appointments/a1/status")).toHaveLength(1));
    expect(bodyOf(f, "POST /appointments/a1/status")).toEqual({ status: "cancelled" });
  });

  it("«Клиент приехал» — без подтверждения; недопустимый переход (409) показывает сообщение из словаря", async () => {
    const { f } = world({ over: { "POST /appointments/a1/status": () => apiError(409, "invalid_transition") } });
    open();
    await waitFor(() => expect(card()).not.toBeNull());
    const u = userEvent.setup();
    await u.click(card() as HTMLElement);
    await u.click(within(await screen.findByRole("dialog", { name: "Запись" })).getByRole("button", { name: "Клиент приехал" }));
    await waitFor(() => expect(calls(f, "POST /appointments/a1/status")).toHaveLength(1));
    expect(bodyOf(f, "POST /appointments/a1/status")).toEqual({ status: "arrived" });
    expect(await screen.findByText(ERROR_MESSAGES.invalid_transition)).toBeInTheDocument();
    expect(screen.queryByText(/SERVER TEXT/)).toBeNull();
  });

  it("запись в конечном статусе: действий и правки нет", async () => {
    world({ appts: [appt({ status: "no_show" })] });
    open();
    await waitFor(() => expect(card()).not.toBeNull());
    const u = userEvent.setup();
    await u.click(card() as HTMLElement);
    const dlg = within(await screen.findByRole("dialog", { name: "Запись" }));
    expect(dlg.queryByRole("button", { name: "Подтвердить" })).toBeNull();
    expect(dlg.queryByRole("button", { name: "Редактировать" })).toBeNull();
    expect(dlg.queryByRole("button", { name: "Отменить" })).toBeNull();
  });

  it("правка записи отправляет только изменённые поля", async () => {
    const { f } = world({ over: { "PATCH /appointments/a1": (r) => json(200, appt({ ...(r.body as object) })) } });
    open();
    await waitFor(() => expect(card()).not.toBeNull());
    const u = userEvent.setup();
    await u.click(card() as HTMLElement);
    await u.click(within(await screen.findByRole("dialog", { name: "Запись" })).getByRole("button", { name: "Редактировать" }));
    const dlg = within(await screen.findByRole("dialog", { name: "Редактирование записи" }));
    expect(dlg.getByLabelText("Начало")).toHaveValue("10:00");
    expect(dlg.getByLabelText("Окончание")).toHaveValue("11:00");
    expect(dlg.getByLabelText("Пост")).toHaveValue("po1");
    // без изменений форма просто закрывается
    fireEvent.change(dlg.getByLabelText("Окончание"), { target: { value: "11:30" } });
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(calls(f, "PATCH /appointments/a1")).toHaveLength(1));
    expect(bodyOf(f, "PATCH /appointments/a1")).toEqual({
      start_at: "2026-11-10T10:00:00+03:00",
      end_at: "2026-11-10T11:30:00+03:00",
    });
  });
});

describe("мобильный вид", () => {
  const evening = appt({ id: "a2", post_id: "po2", start_at: "2026-11-10T14:00:00+03:00", end_at: "2026-11-10T15:00:00+03:00", vehicle: { id: "v2", make: "BMW", model: "X5", plate_number: "Е555КХ99" } });

  it("список записей дня, чипы постов, без сетки; «Новая запись» открывает форму", async () => {
    stubMatchMedia(true);
    const { f } = world({ appts: [appt(), evening] });
    open();
    const list = await screen.findByRole("list", { name: "Записи дня" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.queryByTestId("calendar-grid")).toBeNull();
    expect(screen.queryByRole("group", { name: "Режим" })).toBeNull();
    // порядок по времени
    expect(within(list).getAllByRole("button")[0]).toHaveAttribute("data-appointment", "a1");

    const u = userEvent.setup();
    const chips = within(screen.getByRole("group", { name: "Посты" }));
    await u.click(chips.getByRole("button", { name: "Пост 2" }));
    expect(within(screen.getByRole("list", { name: "Записи дня" })).getAllByRole("listitem")).toHaveLength(1);
    expect(card("a2")).not.toBeNull();
    expect(card("a1")).toBeNull();
    await u.click(chips.getByRole("button", { name: "Все посты" }));
    expect(within(screen.getByRole("list", { name: "Записи дня" })).getAllByRole("listitem")).toHaveLength(2);

    await u.click(card("a1") as HTMLElement);
    expect(await screen.findByRole("dialog", { name: "Запись" })).toBeInTheDocument();
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await u.click(screen.getByRole("button", { name: "Новая запись" }));
    const dlg = within(await screen.findByRole("dialog", { name: "Новая запись" }));
    expect(dlg.getByLabelText("Пост")).toHaveValue("po1");
    // сегодня 12:00: ближайшее время — 12:00
    expect(dlg.getByLabelText("Начало")).toHaveValue("12:00");
    expect(calls(f, "GET /appointments").length).toBeGreaterThan(0);
  });

  it("пустой день", async () => {
    stubMatchMedia(true);
    world({ appts: [] });
    open();
    expect(await screen.findByText("На этот день записей нет")).toBeInTheDocument();
  });
});

describe("безопасность вывода", () => {
  it("<script> в имени клиента, комментарии и услуге — только текст", async () => {
    const evil = "<script>alert(1)</script>";
    const img = "<img src=x onerror=alert(1)>";
    world({
      appts: [appt({ client: { id: "c1", full_name: evil, phone: "+79991234567" }, comment: img, services: [{ id: "s1", name: "<b>Масло</b>" }], vehicle: { id: "v1", make: "<i>Kia</i>", model: "Rio", plate_number: null } })],
    });
    const { container } = open();
    await waitFor(() => expect(card()).not.toBeNull());
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const u = userEvent.setup();
    await u.click(card() as HTMLElement);
    const dlg = within(await screen.findByRole("dialog", { name: "Запись" }));
    expect(dlg.getByText(evil)).toBeInTheDocument();
    expect(dlg.getByText(img)).toBeInTheDocument();
    expect(dlg.getByText("<b>Масло</b>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(document.querySelector("i")).toBeNull();
  });

  it("результаты поиска клиента с разметкой в имени — текст", async () => {
    const evil = "<img src=x onerror=alert(1)>";
    world({ over: { "GET /clients": () => page([{ ...CLIENT, full_name: evil }]) } });
    open();
    const u = userEvent.setup();
    await screen.findByText("Пост 1");
    await u.click(await screen.findByLabelText(slot("Пост 1", "Сервис", "10:15")));
    const dlg = within(await screen.findByRole("dialog", { name: "Новая запись" }));
    await u.type(dlg.getByLabelText("Поиск клиента"), "x<");
    expect(await dlg.findByText(evil)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("точка: часовой пояс и рабочие часы", () => {
  function locWorld(user: User) {
    return mockApi({
      "POST /auth/refresh": () => json(200, session(user)),
      "GET /locations": () => json(200, [LOC1]),
      "GET /locations/l1": () => json(200, LOC1),
      "PATCH /locations/l1": (r) => json(200, { ...LOC1, ...(r.body as object) }),
      "POST /locations": (r) => json(201, { ...LOC1, id: "l9", ...(r.body as object) }),
      "GET /locations/l9": () => json(200, LOC1),
    });
  }

  it("форма показывает значения точки; PATCH только с изменёнными полями расписания", async () => {
    const f = locWorld(makeUser("director"));
    open("/locations/l1");
    const tz = await screen.findByLabelText("Часовой пояс");
    expect(tz).toHaveValue("Europe/Moscow");
    expect(screen.getByLabelText("Начало работы")).toHaveValue("09:00");
    expect(screen.getByLabelText("Конец работы")).toHaveValue("21:00");
    const u = userEvent.setup();
    await u.selectOptions(tz, "Asia/Yekaterinburg");
    fireEvent.change(screen.getByLabelText("Конец работы"), { target: { value: "20:00" } });
    await u.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(calls(f, "PATCH /locations/l1")).toHaveLength(1));
    const body = bodyOf(f, "PATCH /locations/l1");
    expect(body).toMatchObject({ timezone: "Asia/Yekaterinburg", work_end: "20:00" });
    expect(body).not.toHaveProperty("work_start");
  });

  it("окончание работы не позже начала — ошибка без запроса", async () => {
    const f = locWorld(makeUser("director"));
    open("/locations/l1");
    await screen.findByLabelText("Часовой пояс");
    fireEvent.change(screen.getByLabelText("Конец работы"), { target: { value: "08:00" } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Окончание работы должно быть позже начала")).toBeInTheDocument();
    expect(calls(f, "PATCH /locations/l1")).toHaveLength(0);
  });

  it("ошибка сервера по часовому поясу — текст из словаря", async () => {
    mockApi({
      "POST /auth/refresh": () => json(200, session(makeUser("director"))),
      "GET /locations": () => json(200, [LOC1]),
      "GET /locations/l1": () => json(200, LOC1),
      "PATCH /locations/l1": () => apiError(422, "validation_error", { timezone: "invalid" }),
    });
    open("/locations/l1");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByLabelText(/^Часовой пояс/)).toHaveAttribute("aria-invalid", "true"));
    expect(screen.queryByText(/SERVER TEXT/)).toBeNull();
  });

  it("новая точка: расписание уходит только если отличается от значений по умолчанию", async () => {
    const f = locWorld(makeUser("director"));
    open("/locations/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Название"), "Самара");
    await u.type(screen.getByLabelText("Адрес"), "ул. Новая, 3");
    await u.selectOptions(screen.getByLabelText("Часовой пояс"), "Europe/Samara");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(calls(f, "POST /locations")).toHaveLength(1));
    expect(bodyOf(f, "POST /locations")).toEqual({ name: "Самара", address: "ул. Новая, 3", timezone: "Europe/Samara" });
  });
});

describe("словарь ошибок", () => {
  it("новые коды записи заведены и не содержат технических деталей", () => {
    for (const code of ["post_busy", "outside_working_hours", "invalid_transition", "invalid_state"]) {
      expect(ERROR_MESSAGES[code]).toBeTruthy();
      expect(ERROR_MESSAGES[code]).not.toMatch(/sql|trace|exception/i);
    }
  });
});
