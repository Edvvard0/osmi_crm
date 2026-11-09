import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import type { User } from "@/shared/api/types";

import { type Handler, LOC1, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const U = (n: string, name: string) => ({ id: n, full_name: name });
const CLIENT = { id: "c1", full_name: "Пётр Иванов", phone: "+79991234567" };
const VEHICLE = { id: "v1", make: "Toyota", model: "Camry", plate_number: "А123ВС777" };

function item(over: Record<string, unknown> = {}) {
  return {
    id: "i1",
    service_id: "s1",
    name: "Замена масла",
    department: "service",
    quantity: "1.00",
    unit_price: "1500.00",
    discount_percent: "0.00",
    total: "1500.00",
    norm_hours: "0.50",
    norm_hours_total: "0.50",
    mechanic: null,
    status: "pending",
    started_at: null,
    finished_at: null,
    actual_minutes: 0,
    sort_order: 1,
    ...over,
  };
}

function order(over: Record<string, unknown> = {}) {
  return {
    id: "o1",
    number: "MSK1-000001",
    location_id: "l1",
    status: "in_progress",
    department: "service",
    created_at: "2026-11-09T09:00:00+03:00",
    planned_ready_at: "2026-11-09T18:00:00+03:00",
    is_overdue: false,
    mileage_in: 120000,
    client: { ...CLIENT, discount_percent: 0 },
    vehicle: { ...VEHICLE, year: 2018, vin: null, color: null, mileage: 120000 },
    manager: U("u-manager", "Иван manager"),
    mechanics: [],
    items_count: 1,
    items_done_count: 0,
    works_total: "1500.00",
    parts_total: "700.00",
    discount_total: "100.00",
    total: "2100.00",
    paid_total: "500.00",
    balance_due: "1600.00",
    payment_status: "partial",
    version: 3,
    complaint: "Стук",
    intake_notes: null,
    diagnosis: null,
    discount_percent: "5.00",
    started_at: null,
    ready_at: null,
    closed_at: null,
    cancel_reason: null,
    appointment_id: null,
    items: [item()],
    parts: [
      {
        id: "p1",
        part_id: "pp1",
        name: "Фильтр масляный",
        sku: "F-1",
        unit: "pcs",
        quantity: "1.000",
        unit_price: "700.00",
        total: "700.00",
        unit_cost: null,
        in_stock: null,
        added_by: U("u-manager", "Иван manager"),
        created_at: "2026-11-09T09:10:00+03:00",
      },
    ],
    allowed_transitions: ["awaiting_parts", "quality_check", "cancelled"],
    updated_at: "2026-11-09T09:10:00+03:00",
    ...over,
  };
}

function world(user: User, over: Record<string, Handler> = {}) {
  return mockApi({
    "POST /auth/refresh": () => json(200, session(user)),
    "GET /locations": () => json(200, [LOC1]),
    "GET /locations/l1": () => json(200, LOC1),
    "GET /work-orders/summary": () => json(200, { in_progress: 4, awaiting_parts: 1, ready: 2, overdue: 3, open_total: 9 }),
    "GET /appointments": () => json(200, []),
    ...over,
  });
}

function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

const manager = makeUser("manager");

describe("MG-04 список заказов", () => {
  it("таблица: номер, статус, сумма; просроченный срок помечен", async () => {
    const o = order({ is_overdue: true, status: "ready" });
    world(manager, { "GET /work-orders": () => json(200, { items: [o], total: 1, limit: 50, offset: 0 }) });
    open("/orders");
    const link = await screen.findByRole("link", { name: "MSK1-000001" }, { timeout: 4000 });
    expect(link).toHaveAttribute("href", "/orders/o1");
    expect(screen.getAllByText("Готов").length).toBeGreaterThan(0);
    expect(screen.getByText(/2\s?100/)).toBeInTheDocument();
  });

  it("пустой список: подсказка и кнопка «Новый заказ»", async () => {
    world(manager, { "GET /work-orders": () => json(200, { items: [], total: 0, limit: 50, offset: 0 }) });
    open("/orders");
    expect(await screen.findByText("Заказов пока нет")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Новый заказ" }).length).toBeGreaterThan(0);
  });

  it("канбан: карточка падает только в разрешённую колонку, смена статуса несёт version", async () => {
    localStorage.setItem("orders.view", "kanban");
    const card = order({ status: "new", version: 7 });
    const columns = ["new", "diagnostics", "awaiting_approval", "in_progress", "awaiting_parts", "quality_check", "ready", "closed"].map((s) => ({
      status: s,
      total: s === "new" ? 1 : 0,
      items: s === "new" ? [card] : [],
    }));
    const f = world(manager, {
      "GET /work-orders/board": () => json(200, { columns }),
      "POST /work-orders/o1/status": () => json(200, order({ status: "in_progress", version: 8 })),
    });
    open("/orders");
    await screen.findByLabelText("Канбан-доска");
    await screen.findByText("MSK1-000001");
    expect(calls(f, "POST /work-orders/o1/status")).toHaveLength(0);
  });
});

describe("MG-05 карточка заказа", () => {
  it("шапка, степпер, суммы; цена каталожной строки у менеджера только для чтения; «Остаток» — прочерк", async () => {
    world(manager, { "GET /work-orders/o1": () => json(200, order()) });
    open("/orders/o1");
    expect(await screen.findByRole("heading", { name: "MSK1-000001" })).toBeInTheDocument();
    const steps = screen.getByRole("list", { name: "Ход заказа" });
    expect(within(steps).getByText("В работе").closest("li")).toHaveAttribute("aria-current", "step");
    const sums = screen.getByLabelText("Итоги заказа");
    expect(within(sums).getByText(/2\s?100/)).toBeInTheDocument();
    expect(within(sums).getByText(/1\s?600/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /\+7/ })).toHaveAttribute("href", "tel:+79991234567");
    expect(screen.getByLabelText("Цена: Замена масла")).toBeDisabled();
    expect(screen.getByLabelText("Количество: Замена масла")).toBeEnabled();
    await userEvent.setup().click(screen.getByRole("tab", { name: /Запчасти/ }));
    expect(screen.getByText("Остаток")).toBeInTheDocument();
    expect(screen.getByText("Фильтр масляный")).toBeInTheDocument();
  });

  it("«Следующий статус» отправляет version и обновляет карточку", async () => {
    let body: unknown;
    const f = world(manager, {
      "GET /work-orders/o1": () => json(200, order()),
      "POST /work-orders/o1/status": (r) => {
        body = r.body;
        return json(200, order({ status: "quality_check", version: 4, allowed_transitions: ["ready", "in_progress", "cancelled"] }));
      },
    });
    open("/orders/o1");
    await userEvent.setup().click(await screen.findByRole("button", { name: /Следующий статус/ }));
    await waitFor(() => expect(calls(f, "POST /work-orders/o1/status")).toHaveLength(1));
    expect(body).toEqual({ status: "quality_check", version: 3 });
    expect(await screen.findByRole("button", { name: /Следующий статус: Готов/ })).toBeInTheDocument();
  });

  it("409 version_conflict → диалог «Данные изменил другой сотрудник», «Обновить» перечитывает заказ", async () => {
    let gets = 0;
    const f = world(manager, {
      "GET /work-orders/o1": () => {
        gets += 1;
        return json(200, order({ version: gets === 1 ? 3 : 5 }));
      },
      "PATCH /work-orders/o1/items/i1": () => apiError(409, "version_conflict"),
    });
    open("/orders/o1");
    const u = userEvent.setup();
    const qty = await screen.findByLabelText("Количество: Замена масла");
    await u.clear(qty);
    await u.type(qty, "2");
    await u.tab();
    expect(await screen.findByText("Данные изменил другой сотрудник")).toBeInTheDocument();
    expect(calls(f, "PATCH /work-orders/o1/items/i1")).toHaveLength(1);
    await u.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(gets).toBe(2));
    expect(screen.queryByText("Данные изменил другой сотрудник")).toBeNull();
  });
});

describe("MG-06 создание заказа", () => {
  it("из записи: клиент и авто подставлены, в POST уходит appointment_id; appointment_has_order ведёт к существующему заказу", async () => {
    const apt = {
      id: "a1",
      location_id: "l1",
      client_id: "c1",
      vehicle_id: "v1",
      post_id: null,
      department: "service",
      start_at: "2026-11-09T10:00:00+03:00",
      end_at: "2026-11-09T11:00:00+03:00",
      status: "arrived",
      comment: null,
      service_ids: ["s1"],
      services: [{ id: "s1", name: "Замена масла" }],
      client: CLIENT,
      vehicle: VEHICLE,
      work_order_id: null,
      created_by: "u",
      created_at: "2026-11-08T10:00:00Z",
      updated_at: "2026-11-08T10:00:00Z",
    };
    let sent: Record<string, unknown> | undefined;
    const f = world(manager, {
      "GET /appointments/a1": () => json(200, apt),
      "POST /work-orders": (r) => {
        sent = r.body as Record<string, unknown>;
        return json(409, { error: { code: "appointment_has_order", message: "x", fields: {}, details: { work_order_id: "o9", work_order_number: "MSK1-000009" }, request_id: "r" } });
      },
      "GET /work-orders/o9": () => json(200, order({ id: "o9", number: "MSK1-000009" })),
    });
    open("/orders/new?appointment_id=a1");
    expect(await screen.findByText("Пётр Иванов")).toBeInTheDocument();
    expect(screen.getByText("Замена масла")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Создать заказ" }));
    await waitFor(() => expect(calls(f, "POST /work-orders")).toHaveLength(1));
    expect(sent).toMatchObject({ location_id: "l1", client_id: "c1", vehicle_id: "v1", appointment_id: "a1", items: [{ service_id: "s1", quantity: "1.00" }] });
    expect(await screen.findByRole("heading", { name: "MSK1-000009" })).toBeInTheDocument();
  });
});

describe("MG-07 печать", () => {
  it("PDF скачивается через api() и показывается в iframe по blob:-URL; акт недоступен до «Готов»", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test-1"), revokeObjectURL: vi.fn() }));
    const f = world(manager, {
      "GET /work-orders/o1": () => json(200, order()),
      "GET /work-orders/o1/print/work-order": () => new Response(new Blob(["%PDF-1.4"], { type: "application/pdf" }), { status: 200, headers: { "Content-Type": "application/pdf" } }),
    });
    open("/orders/o1/print");
    const frame = await screen.findByTitle("Предпросмотр PDF");
    expect(frame).toHaveAttribute("src", "blob:test-1");
    expect(calls(f, "GET /work-orders/o1/print/work-order")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Акт выполненных работ" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Печать" })).toBeEnabled();
  });
});

describe("MG-01 главная менеджера", () => {
  it("счётчики ведут в список с фильтром; пустая лента записей", async () => {
    world(manager);
    open("/");
    const link = await screen.findByRole("link", { name: /Просрочены/ });
    expect(link).toHaveAttribute("href", "/orders?overdue=true");
    await waitFor(() => expect(within(screen.getByRole("link", { name: /Просрочены/ })).getByText("3")).toBeInTheDocument());
    expect(await screen.findByText("На сегодня записей нет")).toBeInTheDocument();
  });
});
