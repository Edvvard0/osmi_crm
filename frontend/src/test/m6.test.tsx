import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import type { Role } from "@/shared/api/types";
import type { FinishResult, MechanicPartRequest, MechanicTask, MechanicTaskDetail, PartRequestFull, TimerResult } from "@/features/mechanic/types";

import { type Handler, LOC1, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const NOW = "2026-11-10T09:00:00Z";
const VEH = { id: "v1", make: "Toyota", model: "Camry", year: 2015, plate_number: "А123ВС", color: "белый" };

function task(over: Partial<MechanicTask> = {}): MechanicTask {
  return {
    item_id: "i1", order_id: "o1", order_number: "З-0001", order_status: "in_progress", department: "service",
    name: "Замена масла", quantity: "1.00", norm_hours: "1.50", status: "pending", worked_seconds: 0, running_since: null,
    vehicle: VEH, planned_ready_at: null, is_overdue: false, can_start: true, finished_at: null, ...over,
  };
}
function detail(over: Partial<MechanicTaskDetail> = {}): MechanicTaskDetail {
  return {
    ...task(), complaint: "Стук в подвеске", intake_notes: "Царапина на бампере", mileage_in: 120000,
    my_items: [], comments: [], server_time: NOW, ...over,
  };
}
const timer = (t: MechanicTask, active: MechanicTask | null = t): TimerResult => ({ task: t, active, server_time: NOW });

function world(role: Role = "mechanic", over: Record<string, Handler> = {}) {
  const user = makeUser(role);
  return mockApi({
    "POST /auth/refresh": () => json(200, session(user)),
    "GET /locations": () => json(200, [LOC1]),
    "GET /mechanic/tasks": () => json(200, { active: null, items: [], server_time: NOW }),
    ...over,
  });
}

function open(path = "/") {
  window.history.pushState({}, "", path);
  return render(<App />);
}
const bodyOf = (f: ReturnType<typeof mockApi>, key: string, i = 0) => JSON.parse(String(calls(f, key)[i][1]?.body)) as Record<string, unknown>;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(NOW));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("M-01: мои задачи", () => {
  it("активная работа с таймером и список; кнопка «Начать» у ожидающей", async () => {
    const active = task({ item_id: "i1", status: "in_progress", worked_seconds: 3725, running_since: NOW });
    const wait = task({ item_id: "i2", name: "Диагностика", order_number: "З-0002" });
    world("mechanic", { "GET /mechanic/tasks": () => json(200, { active, items: [active, wait], server_time: NOW }) });
    open();
    const cards = await screen.findAllByRole("article");
    const activeCard = cards.find((c) => c.getAttribute("data-task") === "i1") as HTMLElement;
    expect(within(activeCard).getByLabelText("Время работы")).toHaveTextContent("1:02:05");
    expect(within(activeCard).getByRole("button", { name: "Пауза" })).toBeInTheDocument();
    const waitCard = cards.find((c) => c.getAttribute("data-task") === "i2") as HTMLElement;
    expect(within(waitCard).getByRole("button", { name: "Начать" })).toBeInTheDocument();
    expect(screen.getAllByText("А123ВС").length).toBeGreaterThan(0);
  });

  it("another_task_active: диалог и повтор с pause_active: true", async () => {
    const wait = task({ item_id: "i2", name: "Диагностика" });
    let n = 0;
    const f = world("mechanic", {
      "GET /mechanic/tasks": () => json(200, { active: null, items: [wait], server_time: NOW }),
      "POST /mechanic/tasks/i2/start": () => {
        n += 1;
        if (n === 1) {
          return json(409, { error: { code: "another_task_active", message: "x", fields: {}, request_id: "r", details: { item_id: "i1", order_number: "З-0001", item_name: "Замена масла" } } });
        }
        return json(200, timer(task({ item_id: "i2", status: "in_progress", running_since: NOW, worked_seconds: 0 })));
      },
    });
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "Начать" }));
    const dialog = await screen.findByRole("dialog", { name: "Другая работа уже идёт" });
    expect(dialog).toHaveTextContent("Замена масла");
    await user.click(within(dialog).getByRole("button", { name: "Поставить на паузу и начать эту" }));
    await waitFor(() => expect(calls(f, "POST /mechanic/tasks/i2/start")).toHaveLength(2));
    expect(bodyOf(f, "POST /mechanic/tasks/i2/start", 0)).toEqual({});
    expect(bodyOf(f, "POST /mechanic/tasks/i2/start", 1)).toEqual({ pause_active: true });
  });
});

describe("M-02/M-03: карточка работы", () => {
  it("can_start = false: кнопок запуска нет, есть подсказка", async () => {
    world("mechanic", { "GET /mechanic/tasks/i1": () => json(200, detail({ can_start: false, order_status: "awaiting_approval" })) });
    open("/tasks/i1");
    expect(await screen.findByText("Заказ ещё не передан в работу")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Начать" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Завершить" })).not.toBeInTheDocument();
    expect(screen.getByText("Стук в подвеске")).toBeInTheDocument();
  });

  it("завершение: POST finish с комментарием и сообщение об автопереходе заказа", async () => {
    const running = task({ status: "in_progress", worked_seconds: 600, running_since: NOW });
    const done = task({ status: "done", worked_seconds: 600, finished_at: NOW });
    const f = world("mechanic", {
      "GET /mechanic/tasks/i1": () => json(200, detail({ status: "in_progress", worked_seconds: 600, running_since: NOW })),
      "POST /mechanic/tasks/i1/finish": () =>
        json(200, { task: done, active: null, server_time: NOW, order_status: "quality_check", order_auto_moved: true } satisfies FinishResult),
    });
    void running;
    const user = userEvent.setup();
    open("/tasks/i1");
    await user.click(await screen.findByRole("button", { name: "Завершить" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Комментарий (необязательно)"), "Масло и фильтр заменены");
    await user.click(within(dialog).getByRole("button", { name: "Завершить работу" }));
    await waitFor(() => expect(calls(f, "POST /mechanic/tasks/i1/finish")).toHaveLength(1));
    expect(bodyOf(f, "POST /mechanic/tasks/i1/finish")).toEqual({ comment: "Масло и фильтр заменены" });
    expect(await screen.findByText("Все работы заказа выполнены")).toBeInTheDocument();
  });

  it("404 на карточку работы — страница «Не найдено»", async () => {
    world("mechanic", { "GET /mechanic/tasks/zz": () => apiError(404, "not_found") });
    open("/tasks/zz");
    expect(await screen.findByText("Не найдено")).toBeInTheDocument();
  });
});

describe("M-04 – M-06: заявки и рекомендации", () => {
  it("заявка на запчасть: свободный текст и количество уходят строкой Qty3", async () => {
    const created: MechanicPartRequest = {
      id: "p1", order_id: "o1", order_number: "З-0001", item_id: "i1", item_name: "Замена масла", part: null,
      description: "Масляный фильтр", quantity: "2.000", unit: null, status: "new", reject_reason: null, created_at: NOW, handled_at: null,
    };
    const f = world("mechanic", {
      "GET /mechanic/tasks/i1": () => json(200, detail()),
      "POST /mechanic/part-requests": () => json(201, created),
    });
    const user = userEvent.setup();
    open("/tasks/i1/part-request");
    await user.type(await screen.findByLabelText("Что нужно (если нет в справочнике)"), "Масляный фильтр");
    await user.click(screen.getByRole("button", { name: "Больше" }));
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    await waitFor(() => expect(calls(f, "POST /mechanic/part-requests")).toHaveLength(1));
    expect(bodyOf(f, "POST /mechanic/part-requests")).toEqual({ item_id: "i1", description: "Масляный фильтр", quantity: "2.000" });
    expect(await screen.findByText("Заявка отправлена")).toBeInTheDocument();
  });

  it("мои заявки: статус и причина отказа", async () => {
    const rej: MechanicPartRequest = {
      id: "p2", order_id: "o1", order_number: "З-0001", item_id: "i1", item_name: "Замена масла", part: null,
      description: "Сальник", quantity: "1.000", unit: null, status: "rejected", reject_reason: "Нет в наличии", created_at: NOW, handled_at: NOW,
    };
    world("mechanic", { "GET /mechanic/part-requests": () => json(200, { items: [rej], total: 1 }) });
    open("/requests");
    expect(await screen.findByText("Сальник")).toBeInTheDocument();
    expect(screen.getAllByText("Отклонена").length).toBeGreaterThan(0);
    expect(screen.getByText("Причина: Нет в наличии")).toBeInTheDocument();
  });

  it("рекомендация: текст и приоритет уходят на /mechanic/recommendations", async () => {
    const f = world("mechanic", {
      "GET /mechanic/tasks/i1": () => json(200, detail()),
      "POST /mechanic/recommendations": () => json(201, { id: "r1" }),
    });
    const user = userEvent.setup();
    open("/tasks/i1/recommendation");
    await user.type(await screen.findByLabelText("Что рекомендуете"), "Заменить колодки");
    await user.click(screen.getByRole("radio", { name: "Высокий" }));
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(calls(f, "POST /mechanic/recommendations")).toHaveLength(1));
    expect(bodyOf(f, "POST /mechanic/recommendations")).toEqual({ item_id: "i1", text: "Заменить колодки", priority: "high" });
  });
});

describe("MG-11: заявки механиков (менеджер)", () => {
  function pr(over: Partial<PartRequestFull> = {}): PartRequestFull {
    return {
      id: "p1", location_id: "l1", order: { id: "o1", number: "З-0001", status: "awaiting_parts", version: 7 },
      vehicle: { id: "v1", make: "Toyota", model: "Camry", plate_number: "А123ВС" }, item_id: "i1", item_name: "Замена масла",
      mechanic: { id: "m1", full_name: "Пётр Механик" },
      part: { id: "pt1", name: "Фильтр масляный", sku: "F-1", unit: "pcs", sale_price: "500.00", in_stock: "1.000" },
      description: "", quantity: "2.000", status: "new", reject_reason: null, handled_by: null, handled_at: null, created_at: NOW, ...over,
    };
  }

  it("список, одобрение, отклонение с причиной и выдача с версией заказа", async () => {
    const f = world("manager", {
      "GET /part-requests": () => json(200, { items: [pr()], total: 1 }),
      "GET /part-requests/summary": () => json(200, { new: 1, approved: 0 }),
      "POST /part-requests/p1/approve": () => json(200, pr({ status: "approved" })),
      "POST /part-requests/p1/reject": () => json(200, pr({ status: "rejected" })),
      "POST /part-requests/p1/issue": () => json(200, pr({ status: "issued" })),
    });
    const user = userEvent.setup();
    open("/part-requests");
    const row = await screen.findByText("Фильтр масляный");
    expect(row).toBeInTheDocument();
    expect(screen.getByText(/остаток: 1/)).toHaveClass("text-danger");
    expect(screen.getByRole("link", { name: "З-0001" })).toHaveAttribute("href", "/orders/o1");

    await user.click(screen.getByRole("button", { name: "Одобрить" }));
    await waitFor(() => expect(calls(f, "POST /part-requests/p1/approve")).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "Отклонить" }));
    const rd = await screen.findByRole("dialog", { name: "Отклонить заявку" });
    await user.click(within(rd).getByRole("button", { name: "Отклонить" }));
    expect(await within(rd).findByText(/Укажите причину отказа/)).toBeInTheDocument();
    expect(calls(f, "POST /part-requests/p1/reject")).toHaveLength(0);
    await user.type(within(rd).getByRole("textbox"), "Нет на складе");
    await user.click(within(rd).getByRole("button", { name: "Отклонить" }));
    await waitFor(() => expect(calls(f, "POST /part-requests/p1/reject")).toHaveLength(1));
    expect(bodyOf(f, "POST /part-requests/p1/reject")).toEqual({ reason: "Нет на складе" });

    await user.click(await screen.findByRole("button", { name: "Выдать" }));
    const id = await screen.findByRole("dialog", { name: "Выдать запчасть" });
    await user.click(within(id).getByRole("button", { name: "Выдать" }));
    await waitFor(() => expect(calls(f, "POST /part-requests/p1/issue")).toHaveLength(1));
    expect(bodyOf(f, "POST /part-requests/p1/issue")).toEqual({ version: 7, quantity: "2.000" });
  });
});
