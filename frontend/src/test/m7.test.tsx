import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { LocationTelegram } from "@/features/telegram/LocationTelegram";
import { ERROR_MESSAGES } from "@/shared/api/errors";
import { ToastProvider } from "@/shared/ui/toast";
import type { CrmLocation, User } from "@/shared/api/types";

import { type Handler, LOC1, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

afterEach(() => vi.useRealTimers());

const SETTINGS = [
  { event_type: "appointment.created", title: "Новая запись", description: "", is_enabled: true, is_default: true },
  { event_type: "stock.low", title: "Низкий остаток", description: "", is_enabled: true, is_default: true },
];

function world(user: User, over: Record<string, Handler> = {}, locs: CrmLocation[] = [LOC1]) {
  return mockApi({
    "POST /auth/refresh": () => json(200, session(user)),
    "GET /locations": () => json(200, locs),
    "GET /locations/l1": () => json(200, locs[0]),
    "GET /users": () => json(200, { items: [{ ...makeUser("mechanic"), telegram_linked: true }, { ...makeUser("manager"), id: "u2", telegram_linked: false }], total: 2 }),
    ...over,
  });
}

function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

describe("C-02 секция Telegram", () => {
  it("Telegram выключен → пояснение, без кнопки привязки", async () => {
    world(makeUser("manager"), { "GET /telegram/status": () => json(200, { enabled: false, bot_username: null, linked: false, telegram_username: null }) });
    open("/settings");
    expect(await screen.findByText("Telegram не настроен, обратитесь к руководителю")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Привязать Telegram" })).toBeNull();
  });

  it("привязка: код, ссылка на бота, опрос статуса до linked, затем переключатели", async () => {
    let linked = false;
    let statusCalls = 0;
    const f = world(makeUser("manager"), {
      "GET /telegram/status": () => {
        statusCalls += 1;
        return json(200, { enabled: true, bot_username: "crm_bot", linked, telegram_username: linked ? "ivan" : null });
      },
      "POST /telegram/link-code": () =>
        json(201, { code: "AB23CD45", link: "https://t.me/crm_bot?start=AB23CD45", expires_at: new Date(Date.now() + 600_000).toISOString() }),
      "GET /telegram/notification-settings": () => json(200, SETTINGS),
    });
    open("/settings");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Привязать Telegram" }));
    expect(await screen.findByTestId("tg-code")).toHaveTextContent("AB23CD45");
    expect(screen.getByRole("link", { name: "Открыть в Telegram" })).toHaveAttribute("href", "https://t.me/crm_bot?start=AB23CD45");
    expect(calls(f, "POST /telegram/link-code")).toHaveLength(1);
    const before = statusCalls;
    linked = true;
    await waitFor(() => expect(statusCalls).toBeGreaterThan(before), { timeout: 5000 });
    expect(await screen.findByText("@ivan", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(await screen.findByRole("switch", { name: "Новая запись" })).toBeChecked();
    expect(screen.queryByTestId("tg-code")).toBeNull();
  }, 15000);

  it("already_linked и rate_limited показываются под кнопкой", async () => {
    let n = 0;
    world(makeUser("mechanic"), {
      "GET /telegram/status": () => json(200, { enabled: true, bot_username: "b", linked: false, telegram_username: null }),
      "POST /telegram/link-code": () => (n++ === 0 ? apiError(409, "already_linked") : apiError(429, "rate_limited")),
    });
    open("/settings");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Привязать Telegram" }));
    expect(await screen.findByText(ERROR_MESSAGES.already_linked)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Привязать Telegram" }));
    expect(await screen.findByText(ERROR_MESSAGES.rate_limited)).toBeInTheDocument();
  });

  it("переключатель сохраняется сразу; при ошибке откатывается; отвязка с подтверждением", async () => {
    let fail = false;
    let linked = true;
    const f = world(makeUser("manager"), {
      "GET /telegram/status": () => json(200, { enabled: true, bot_username: "b", linked, telegram_username: linked ? "ivan" : null }),
      "GET /telegram/notification-settings": () => json(200, SETTINGS),
      "PATCH /telegram/notification-settings": (r) => {
        if (fail) return apiError(422, "validation_error", { items: "bad" });
        const it = (r.body as { items: { event_type: string; is_enabled: boolean }[] }).items[0];
        return json(200, SETTINGS.map((s) => (s.event_type === it.event_type ? { ...s, is_enabled: it.is_enabled, is_default: false } : s)));
      },
      "DELETE /telegram/link": () => {
        linked = false;
        return json(204);
      },
    });
    open("/settings");
    const u = userEvent.setup();
    const sw = await screen.findByRole("switch", { name: "Низкий остаток" });
    await u.click(sw);
    await waitFor(() => expect(calls(f, "PATCH /telegram/notification-settings")).toHaveLength(1));
    expect(JSON.parse(String(calls(f, "PATCH /telegram/notification-settings")[0][1]?.body))).toEqual({ items: [{ event_type: "stock.low", is_enabled: false }] });
    await waitFor(() => expect(screen.getByRole("switch", { name: "Низкий остаток" })).not.toBeChecked());

    fail = true;
    await u.click(screen.getByRole("switch", { name: "Новая запись" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Новая запись" })).toBeChecked());

    await u.click(screen.getByRole("button", { name: "Отключить" }));
    const dlg = await screen.findByRole("dialog", { name: "Отключить Telegram?" });
    expect(calls(f, "DELETE /telegram/link")).toHaveLength(0);
    await u.click(within(dlg).getByRole("button", { name: "Подтвердить отключение" }));
    await waitFor(() => expect(calls(f, "DELETE /telegram/link")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Привязать Telegram" })).toBeInTheDocument();
  });
});

describe("D-06 чат точки и D-04 колонка", () => {
  it("директор: сохраняет ID чата и отправляет тест; ошибка 502 отображается", async () => {
    let tests = 0;
    const f = world(makeUser("director"), {
      "GET /locations/l1": () => json(200, { ...LOC1, has_telegram_chat: true, telegram_chat_id: -100123 }),
      "PATCH /locations/l1": (r) => json(200, { ...LOC1, has_telegram_chat: true, telegram_chat_id: (r.body as { telegram_chat_id: number }).telegram_chat_id }),
      "POST /locations/l1/telegram-test": () => (tests++ === 0 ? json(200, { sent: true }) : apiError(502, "telegram_unavailable")),
    });
    open("/locations/l1");
    const u = userEvent.setup();
    const input = await screen.findByLabelText("ID чата");
    expect(input).toHaveValue("-100123");
    await u.clear(input);
    await u.type(input, "abc");
    await u.click(screen.getByRole("button", { name: "Сохранить чат" }));
    expect(await screen.findByText(/целое число/)).toBeInTheDocument();
    expect(calls(f, "PATCH /locations/l1")).toHaveLength(0);
    await u.clear(input);
    await u.type(input, "-100777");
    await u.click(screen.getByRole("button", { name: "Сохранить чат" }));
    await waitFor(() => expect(calls(f, "PATCH /locations/l1")).toHaveLength(1));
    expect(JSON.parse(String(calls(f, "PATCH /locations/l1")[0][1]?.body))).toEqual({ telegram_chat_id: -100777 });
    await u.click(screen.getByRole("button", { name: "Отправить тест" }));
    expect(await screen.findByText("Тестовое сообщение отправлено")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Отправить тест" }));
    expect(await screen.findByText(ERROR_MESSAGES.telegram_unavailable)).toBeInTheDocument();
  });

  it("менеджер видит только статус, список сотрудников показывает колонку Telegram", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <LocationTelegram loc={{ ...LOC1, has_telegram_chat: false, telegram_chat_id: null }} isDirector={false} />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Чат не подключён")).toBeInTheDocument();
    expect(screen.queryByLabelText("ID чата")).toBeNull();
    expect(screen.queryByRole("button", { name: "Отправить тест" })).toBeNull();
    cleanup();

    world(makeUser("director"));
    open("/users");
    expect((await screen.findAllByText("Telegram подключён")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Да").length).toBeGreaterThan(0);
  });
});
