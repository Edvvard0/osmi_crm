import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { ERROR_MESSAGES } from "@/shared/api/errors";
import type { User } from "@/shared/api/types";
import { fmtQty, incQty, lineTotal, parseQty } from "@/features/stock/format";
import type { StockBalance, StockMovement } from "@/features/stock/types";

import { type Handler, LOC1, calls, json, makeUser, mockApi, session } from "./mockApi";

const base = (user: User): Record<string, Handler> => ({
  "POST /auth/refresh": () => json(200, session(user)),
  "GET /locations": () => json(200, [LOC1]),
  "GET /part-requests/summary": () => json(200, { new: 0, approved: 0 }),
});

function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

const brief = (o = {}) => ({
  id: "p1", sku: "OIL-5W30", name: "Масло 5W-30", brand: "Castrol", barcode: "4600000000011", unit: "l" as const,
  department: "both" as const, sale_price: "900.00", is_active: true, ...o,
});
const bal = (o: Partial<StockBalance> = {}): StockBalance => ({
  location_id: "l1", part: brief(), quantity: "2.000", min_quantity: "5.000", avg_cost: "500.00", stock_value: "1000.00",
  is_low: true, updated_at: "2026-11-01T10:00:00Z", ...o,
});
const mv = (o: Partial<StockMovement> = {}): StockMovement => ({
  id: "m1", location_id: "l1", part: { id: "p1", sku: "OIL-5W30", name: "Масло 5W-30", unit: "l" }, movement_type: "receipt",
  quantity: "10.000", unit_cost: "500.00", total: "5000.00", balance_after: "12.000", work_order: null, related_movement_id: null,
  reversed: false, supplier: "ООО Поставщик", document_number: "Н-1", reason: null, created_by: { id: "u1", full_name: "Иван" },
  created_at: new Date().toISOString(), ...o,
});
const stockPage = (items: StockBalance[]) =>
  json(200, { items, total: items.length, totals: { positions: items.length, low_count: items.filter((i) => i.is_low).length, stock_value: "1000.00" } });

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.unstubAllGlobals());

describe("склад: форматирование", () => {
  it("количества и суммы без float", () => {
    expect(fmtQty("5.000")).toBe("5");
    expect(fmtQty("2.500")).toBe("2,5");
    expect(parseQty("0")).toBeNull();
    expect(parseQty("1,5")).toBe("1.500");
    expect(incQty("1,5")).toBe("2,5");
    expect(lineTotal("2.500", "10.01")).toBe("25.03");
  });
  it("коды ошибок зарегистрированы", () => {
    expect(ERROR_MESSAGES.stock_changed).toBe("Остатки изменились, обновите страницу");
    expect(ERROR_MESSAGES.already_reversed).toBeTruthy();
  });
});

describe("остатки", () => {
  it("механик: нет доступа, запросов склада нет", async () => {
    const f = mockApi(base(makeUser("mechanic")));
    open("/stock");
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
    expect(calls(f, "GET /stock")).toHaveLength(0);
  });

  it("менеджер: таблица, дефицит красным, итоги, фильтр «Только дефицит» и поиск", async () => {
    const f = mockApi({ ...base(makeUser("manager")), "GET /stock": () => stockPage([bal()]) });
    open("/stock");
    const links = await screen.findAllByRole("link", { name: "Масло 5W-30" }, { timeout: 5000 });
    expect(links.length).toBeGreaterThan(0);
    const row = screen.getAllByRole("row").find((r) => within(r).queryByText("Масло 5W-30"))!;
    expect(within(row).getByText("2")).toHaveClass("text-danger");
    expect(within(screen.getByLabelText("Итоги")).getByText("Стоимость склада")).toBeInTheDocument();
    expect(calls(f, "GET /stock")[0][0]).toContain("location_id=l1");
    await userEvent.click(screen.getByLabelText("Только дефицит"));
    await waitFor(() => expect(calls(f, "GET /stock").some(([u]) => String(u).includes("scope=low"))).toBe(true));
    await userEvent.type(screen.getByLabelText("Поиск"), "4600");
    await waitFor(() => expect(calls(f, "GET /stock").some(([u]) => String(u).includes("search=4600"))).toBe(true));
  });

  it("пустой склад", async () => {
    mockApi({ ...base(makeUser("director")), "GET /stock": () => stockPage([]) });
    open("/stock");
    expect(await screen.findByText("На складе пока ничего нет")).toBeInTheDocument();
  });
});

describe("приход (MG-12)", () => {
  it("сканер: Enter по штрихкоду добавляет строку, повтор увеличивает количество; проведение", async () => {
    const f = mockApi({
      ...base(makeUser("manager")),
      "GET /stock": () => stockPage([]),
      "GET /parts": () => json(200, { items: [brief()], total: 1 }),
      "POST /stock/receipts": () => json(201, { movements: [mv()] }),
    });
    open("/stock/receipt");
    const picker = await screen.findByLabelText("Добавить позицию");
    expect(screen.getByRole("button", { name: "Провести приход" })).toBeDisabled();
    await userEvent.type(picker, "4600000000011{Enter}");
    const qty = await screen.findByLabelText(/Количество/);
    expect(qty).toHaveValue("1");
    await userEvent.type(screen.getByLabelText("Добавить позицию"), "4600000000011{Enter}");
    await waitFor(() => expect(screen.getByLabelText(/Количество/)).toHaveValue("2"));
    await userEvent.type(screen.getByLabelText("Цена закупки, ₽"), "500");
    expect(screen.getAllByText(/1\s000,00/).length).toBeGreaterThan(0);
    await userEvent.type(screen.getByLabelText("Поставщик"), "ООО Поставщик");
    await userEvent.click(screen.getByRole("button", { name: "Провести приход" }));
    await waitFor(() => expect(calls(f, "POST /stock/receipts")).toHaveLength(1));
    expect(JSON.parse(String(calls(f, "POST /stock/receipts")[0][1]?.body))).toEqual({
      location_id: "l1",
      supplier: "ООО Поставщик",
      items: [{ part_id: "p1", quantity: "2.000", unit_cost: "500.00" }],
    });
    expect(await screen.findByText("Приход проведён")).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: /Остатки/ })).toBeInTheDocument();
  });
});

describe("списание", () => {
  it("insufficient_stock → сообщение «нужно N, доступно M»", async () => {
    mockApi({
      ...base(makeUser("manager")),
      "GET /stock": () => stockPage([bal()]),
      "GET /parts": () => json(200, { items: [brief()], total: 1 }),
      "POST /stock/write-offs": () =>
        json(409, { error: { code: "insufficient_stock", fields: {}, details: { part_id: "p1", available: "2.000", requested: "5.000" } } }),
    });
    open("/stock");
    await userEvent.click(await screen.findByRole("button", { name: "Списание" }));
    const dlg = await screen.findByRole("dialog", { name: "Списание" });
    await userEvent.type(within(dlg).getByLabelText("Добавить позицию"), "масло");
    await userEvent.click(await within(dlg).findByRole("button", { name: /Масло 5W-30/ }));
    await userEvent.clear(within(dlg).getByLabelText(/Количество/));
    await userEvent.type(within(dlg).getByLabelText(/Количество/), "5");
    await userEvent.type(within(dlg).getByLabelText("Причина"), "Брак");
    await userEvent.click(within(dlg).getByRole("button", { name: "Списать" }));
    expect((await within(dlg).findAllByText(/Недостаточно на складе \(«Масло 5W-30»\): нужно 5, доступно 2/)).length).toBeGreaterThan(0);
  });
});

describe("инвентаризация и сторно", () => {
  it("отправляются только расхождения, показывается итог; stock_changed", async () => {
    let attempt = 0;
    const f = mockApi({
      ...base(makeUser("manager")),
      "GET /stock": () => stockPage([bal({ is_low: false }), bal({ part: brief({ id: "p2", sku: "F-1", name: "Фильтр" }), quantity: "4.000", is_low: false })]),
      "POST /stock/inventory/commit": () =>
        ++attempt === 1
          ? json(409, { error: { code: "stock_changed", fields: {}, details: { part_id: "p1" } } })
          : json(201, { movements: [mv({ movement_type: "adjustment", quantity: "-1.000" })], skipped: 0 }),
    });
    open("/stock/inventory");
    await userEvent.click(await screen.findByRole("button", { name: "Загрузить остатки" }));
    const input = await screen.findByLabelText("Фактически: Масло 5W-30");
    expect(screen.getByRole("button", { name: "Провести" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "1");
    await userEvent.click(screen.getByRole("button", { name: "Провести" }));
    await userEvent.click(await screen.findByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByText("Остатки изменились, обновите страницу")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Провести" }));
    await userEvent.click(await screen.findByRole("button", { name: "Подтвердить" }));
    expect(await screen.findByText(/скорректировано 1, без изменений 1/)).toBeInTheDocument();
    expect(JSON.parse(String(calls(f, "POST /stock/inventory/commit")[1][1]?.body)).items).toEqual([
      { part_id: "p1", expected_quantity: "2.000", actual_quantity: "1.000" },
    ]);
  });

  it("сторно доступно только для прихода/списания/корректировки, уходит с причиной", async () => {
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /stock/movements": () =>
        json(200, {
          items: [
            mv(),
            mv({ id: "m2", movement_type: "issue_to_order", quantity: "-1.000", work_order: { id: "o1", number: "ЗН-1" }, supplier: null, document_number: null }),
          ],
          total: 2,
        }),
      "POST /stock/movements/m1/reverse": () => json(201, mv({ id: "m3", movement_type: "adjustment", quantity: "-10.000" })),
    });
    open("/stock/movements");
    const btns = await screen.findAllByRole("button", { name: /Сторно/ });
    expect(btns.length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("link", { name: "ЗН-1" }))[0]).toHaveAttribute("href", "/orders/o1");
    await userEvent.click(btns[0]);
    const dlg = await screen.findByRole("dialog", { name: "Сторно движения" });
    await userEvent.type(within(dlg).getByLabelText("Причина"), "Ошибка ввода");
    await userEvent.click(within(dlg).getByRole("button", { name: "Сторнировать" }));
    await waitFor(() => expect(calls(f, "POST /stock/movements/m1/reverse")).toHaveLength(1));
    expect(JSON.parse(String(calls(f, "POST /stock/movements/m1/reverse")[0][1]?.body))).toEqual({ reason: "Ошибка ввода" });
  });
});
