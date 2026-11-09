import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "@/app/queryClient";
import { CashPage } from "@/features/cash/CashPage";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { PaymentDialog } from "@/features/cash/PaymentDialog";
import { cashErrorText, fromCents, toCents } from "@/features/cash/lib";
import type { CashOperation, CashReport } from "@/features/cash/types";
import { AppError, ERROR_MESSAGES } from "@/shared/api/errors";
import { ToastProvider } from "@/shared/ui/toast";
import type { Role } from "@/shared/api/types";

import { type Handler, LOC1, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const U = { id: "u1", full_name: "Мария Кассир" };

const REPORT: CashReport = {
  location_id: "l1",
  date_from: "2026-11-09",
  date_to: "2026-11-09",
  timezone: "Europe/Moscow",
  payments: [
    { method: "cash", received: "5000.00", refunded: "500.00", net: "4500.00" },
    { method: "card", received: "3000.00", refunded: "0.00", net: "3000.00" },
    { method: "transfer", received: "0.00", refunded: "0.00", net: "0.00" },
    { method: "other", received: "0.00", refunded: "0.00", net: "0.00" },
  ],
  received_total: "8000.00",
  refunded_total: "500.00",
  net_total: "7500.00",
  expenses_by_method: [{ method: "cash", total: "1200.00" }],
  expenses_by_category: [{ category: { id: "c1", name: "Аренда" }, total: "1200.00" }],
  expenses_total: "1200.00",
  cash_balance: "3300.00",
};

const OPS: CashOperation[] = [
  { kind: "payment", id: "p1", at: "2026-11-09T09:00:00Z", method: "cash", amount: "5000.00", signed_amount: "5000.00", order: { id: "o1", number: "MSK1-000001" }, category: null, comment: null, user: U, is_cancelled: false, refundable: "4500.00" },
  { kind: "refund", id: "r1", at: "2026-11-09T09:30:00Z", method: "cash", amount: "500.00", signed_amount: "-500.00", order: { id: "o1", number: "MSK1-000001" }, category: null, comment: "Ошибка в чеке", user: U, is_cancelled: false, refundable: null },
  { kind: "expense", id: "e1", at: "2026-11-09T10:00:00Z", method: "cash", amount: "1200.00", signed_amount: "-1200.00", order: null, category: { id: "c1", name: "Аренда" }, comment: null, user: U, is_cancelled: false, refundable: null },
  { kind: "expense", id: "e2", at: "2026-11-09T11:00:00Z", method: "card", amount: "99.00", signed_amount: "-99.00", order: null, category: { id: "c2", name: "Реклама" }, comment: null, user: U, is_cancelled: true, refundable: null },
];

function world(role: Role, over: Record<string, Handler> = {}, ops: CashOperation[] = OPS) {
  const user = makeUser(role);
  return mockApi({
    "POST /auth/refresh": () => json(200, session(user)),
    "GET /locations": () => json(200, [LOC1]),
    "GET /cash/report": () => json(200, REPORT),
    "GET /cash/operations": () => json(200, { items: ops, total: ops.length }),
    "GET /expense-categories": () =>
      json(200, [
        { id: "c1", name: "Аренда", is_active: true },
        { id: "c2", name: "Реклама", is_active: true },
      ]),
    ...over,
  });
}

function open(path = "/cash") {
  // Страница монтируется напрямую (без App): тест не зависит от маршрутов других модулей.
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <AuthGate />
          </MemoryRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}
function AuthGate() {
  const { user } = useAuth();
  return user ? <CashPage /> : null;
}
const bodyOf = (f: ReturnType<typeof mockApi>, key: string) => JSON.parse(String(calls(f, key)[0][1]?.body)) as Record<string, unknown>;

describe("касса: чистые функции и сообщения", () => {
  it("копейки и тексты ошибок с суммами из details", () => {
    expect(toCents("1500.50")).toBe(150050);
    expect(fromCents(150050)).toBe("1500.50");
    expect(fromCents(-5)).toBe("-0.05");
    expect(cashErrorText(new AppError("overpayment", 409, {}, undefined, undefined, { balance_due: "700.00" }))).toContain("700,00");
    expect(cashErrorText(new AppError("refund_exceeds_payment", 409, {}, undefined, undefined, { refundable: "100.00" }))).toContain("100,00");
    expect(ERROR_MESSAGES.nothing_to_pay).toBeTruthy();
    expect(ERROR_MESSAGES.refund_exceeds_payment).toBeTruthy();
  });
});

describe("MG-13 касса", () => {
  it("директор: итоги, операции со знаками, отменённый расход зачёркнут, фильтры уходят в запрос", async () => {
    const f = world("director");
    open();
    expect(await screen.findByRole("heading", { name: "Касса" })).toBeInTheDocument();
    expect(await screen.findByTestId("cash-balance")).toHaveTextContent("3 300,00");
    expect(screen.getByTestId("expenses-total")).toHaveTextContent("1 200,00");
    const summary = within(screen.getByRole("region", { name: "Итоги по способам оплаты" }));
    expect(summary.getByText("Наличные")).toBeInTheDocument();
    expect(summary.getByText("Перевод")).toBeInTheDocument();

    const rows = document.querySelectorAll<HTMLElement>("tr[data-kind]");
    expect(rows).toHaveLength(4);
    expect(within(rows[1]).getByText(/−500,00/)).toBeInTheDocument();
    expect(within(rows[0]).getByText(/\+5\s?000,00/)).toBeInTheDocument();
    expect(within(rows[3]).getByText("Отменён")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Расход")).toHaveClass("line-through");
    // директору доступны «Вернуть» (платёж) и «Отменить» (только неотменённый расход)
    expect(screen.getAllByRole("button", { name: /^Вернуть/ })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /^Отменить расход/ })).toHaveLength(1);

    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText("Тип"), "refund");
    await waitFor(() => expect(calls(f, "GET /cash/operations").some(([i]) => String(i).includes("kind=refund"))).toBe(true));
    expect(String(calls(f, "GET /cash/report")[0][0])).toContain("location_id=l1");
  });

  it("менеджер: нет «Вернуть» и «Отменить»; пусто и ошибка загрузки", async () => {
    world("manager", {}, OPS);
    const { unmount } = open();
    await screen.findByTestId("cash-balance");
    expect(screen.queryByRole("button", { name: /^Вернуть/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Отменить/ })).toBeNull();
    unmount();

    world("manager", {}, []);
    const r2 = open();
    expect(await screen.findByText("Операций за выбранный день нет")).toBeInTheDocument();
    r2.unmount();

    let fail = true;
    world("manager", { "GET /cash/report": () => (fail ? apiError(404, "not_found") : json(200, REPORT)) });
    open();
    expect(await screen.findByText(/Не удалось загрузить кассу/)).toBeInTheDocument();
    fail = false;
    await userEvent.setup().click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByTestId("cash-balance")).toBeInTheDocument();
  });

  it("расход: проверка полей на клиенте, затем POST /expenses с точкой, категорией и датой", async () => {
    const f = world("manager", {
      "POST /expenses": () => json(201, { id: "e9" }),
    });
    open();
    const u = userEvent.setup();
    await screen.findByTestId("cash-balance");
    await u.click(screen.getByRole("button", { name: "Расход" }));
    const dlg = within(await screen.findByRole("dialog", { name: "Новый расход" }));
    await u.click(dlg.getByRole("button", { name: "Добавить расход" }));
    expect(dlg.getByText("Выберите категорию")).toBeInTheDocument();
    expect(dlg.getByText("Введите сумму больше нуля")).toBeInTheDocument();
    expect(calls(f, "POST /expenses")).toHaveLength(0);

    await u.selectOptions(dlg.getByLabelText(/^Категория/), "c2");
    await u.type(dlg.getByLabelText(/^Сумма/), "350,5");
    await u.click(dlg.getByRole("button", { name: "Добавить расход" }));
    await waitFor(() => expect(calls(f, "POST /expenses")).toHaveLength(1));
    const b = bodyOf(f, "POST /expenses");
    expect(b).toMatchObject({ location_id: "l1", category_id: "c2", amount: "350.50", method: "cash" });
    expect(b.expense_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Новый расход" })).toBeNull());
  });

  it("возврат (директор): причина обязательна, сумма ≤ refundable, POST /payments/{id}/refund с client_request_id", async () => {
    const f = world("director", {
      "POST /payments/p1/refund": () => json(201, { payment: {}, order: {} }),
    });
    open();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /^Вернуть/ }));
    const dlg = within(await screen.findByRole("dialog", { name: "Возврат оплаты" }));
    expect(dlg.getByLabelText(/^Сумма возврата/)).toHaveValue("4500,00");

    await u.click(dlg.getByRole("button", { name: "Оформить возврат" }));
    expect(dlg.getByText(/Укажите причину возврата/)).toBeInTheDocument();
    expect(calls(f, "POST /payments/p1/refund")).toHaveLength(0);

    await u.clear(dlg.getByLabelText(/^Сумма возврата/));
    await u.type(dlg.getByLabelText(/^Сумма возврата/), "9999");
    await u.type(dlg.getByLabelText("Причина возврата"), "Клиент отказался");
    await u.click(dlg.getByRole("button", { name: "Оформить возврат" }));
    expect(dlg.getByText(/Сумма больше доступной к возврату/)).toBeInTheDocument();

    await u.clear(dlg.getByLabelText(/^Сумма возврата/));
    await u.type(dlg.getByLabelText(/^Сумма возврата/), "1000");
    await u.click(dlg.getByRole("button", { name: "Оформить возврат" }));
    await waitFor(() => expect(calls(f, "POST /payments/p1/refund")).toHaveLength(1));
    const b = bodyOf(f, "POST /payments/p1/refund");
    expect(b).toMatchObject({ amount: "1000.00", comment: "Клиент отказался" });
    expect(String(b.client_request_id)).toMatch(/[0-9a-f-]{8,}/);
  });
});

describe("MG-14 диалог приёма оплаты", () => {
  function renderDialog(order = { id: "o1", number: "MSK1-000001", balance_due: "2000.00" }) {
    const onClose = () => undefined;
    return render(
      <QueryClientProvider client={createQueryClient()}>
        <PaymentDialog order={order} onClose={onClose} />
      </QueryClientProvider>,
    );
  }

  it("остаток по умолчанию, сдача для наличных, один POST при двойном клике, нормализованная сумма и client_request_id", async () => {
    const f = mockApi({
      // медленный ответ (Promise): fetch-подмена его дожидается, повторный клик за это время должен быть проигнорирован
      "POST /work-orders/o1/payments": (async () => {
        await new Promise((r) => setTimeout(r, 30));
        return json(201, { payment: { id: "p9" }, order: { id: "o1" } });
      }) as unknown as Handler,
    });
    renderDialog();
    const u = userEvent.setup();
    const dlg = within(screen.getByRole("dialog", { name: "Приём оплаты" }));
    expect(dlg.getByTestId("balance-due")).toHaveTextContent("2 000,00");
    expect(dlg.getByLabelText(/^Сумма/)).toHaveValue("2000,00");
    expect(dlg.getByRole("button", { name: "Наличные" })).toHaveAttribute("aria-pressed", "true");

    await u.type(dlg.getByLabelText("Получено"), "2500");
    expect(dlg.getByText(/Сдача:/).parentElement).toHaveTextContent("500,00");
    // для карты поле «Получено» не показывается
    await u.click(dlg.getByRole("button", { name: "Карта" }));
    expect(dlg.queryByLabelText("Получено")).toBeNull();

    await u.clear(dlg.getByLabelText(/^Сумма/));
    await u.type(dlg.getByLabelText(/^Сумма/), "1 200,5");
    const submit = dlg.getByRole("button", { name: "Принять оплату" });
    await u.dblClick(submit);
    await waitFor(() => expect(calls(f, "POST /work-orders/o1/payments")).toHaveLength(1));
    const b = bodyOf(f, "POST /work-orders/o1/payments");
    expect(b).toMatchObject({ amount: "1200.50", method: "card" });
    expect(b).not.toHaveProperty("received");
    expect(String(b.client_request_id).length).toBeGreaterThan(8);
  });

  it("overpayment: сообщение с остатком из details, диалог остаётся открытым", async () => {
    mockApi({
      "POST /work-orders/o1/payments": () =>
        json(409, { error: { code: "overpayment", message: "SERVER TEXT", fields: {}, request_id: "r", details: { balance_due: "700.00" } } }),
    });
    renderDialog();
    const u = userEvent.setup();
    const dlg = within(screen.getByRole("dialog", { name: "Приём оплаты" }));
    await u.click(dlg.getByRole("button", { name: "Принять оплату" }));
    expect(await dlg.findByRole("alert")).toHaveTextContent("Сумма больше остатка к оплате: 700,00");
    expect(screen.queryByText("SERVER TEXT")).toBeNull();
  });
});
