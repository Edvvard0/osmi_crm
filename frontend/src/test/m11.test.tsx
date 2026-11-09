import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { formatAuditTime } from "@/features/audit/AuditPage";
import { validate } from "@/features/audit/SystemSettingsPage";
import type { AuditEntry, SystemSettings, UserSession } from "@/features/audit/types";
import type { User } from "@/shared/api/types";

import { type Handler, LOC1, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const base = (user: User): Record<string, Handler> => ({
  "POST /auth/refresh": () => json(200, session(user)),
  "GET /locations": () => json(200, [LOC1]),
});
function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}
afterEach(() => vi.unstubAllGlobals());

const META = {
  actions: [{ value: "update", label: "Изменение" }, { value: "login", label: "Вход" }],
  entity_types: [{ value: "work_order", label: "Заказ-наряд" }, { value: "client", label: "Клиент" }],
};
const entry = (o: Partial<AuditEntry> = {}): AuditEntry => ({
  id: 1,
  created_at: "2026-11-10T21:30:00Z",
  user: { id: "u1", full_name: "Пётр Иванов" },
  action: "update",
  entity_type: "work_order",
  entity_id: "11111111-2222-3333-4444-555555555555",
  entity_label: "ЗН-0001",
  entity_path: "/orders/o1",
  location: { id: "l1", name: "Москва-1", timezone: "Europe/Moscow" },
  changes: { status: { old: "new", new: "in_progress" }, password: "***" },
  ip: "10.0.0.1",
  user_agent: "Chrome",
  ...o,
});
const SETTINGS: SystemSettings = {
  discount_alert_percent: "20.00",
  daily_summary_time: "21:00",
  session_retention_days: 30,
  heatmap_thresholds: { hours: [2, 5, 8], actions: [5, 15, 30] },
  updated_at: null,
  updated_by: null,
};

describe("журнал действий D-08", () => {
  it("менеджер: нет пункта меню и доступа к /audit", async () => {
    const f = mockApi({ ...base(makeUser("manager")) });
    open("/audit");
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Журнал действий" })).toBeNull();
    expect(calls(f, "GET /audit-log")).toHaveLength(0);
  });

  it("руководитель: лента, время в поясе точки, раскрытие «было → стало», «Показать ещё»", async () => {
    const user = userEvent.setup();
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /audit-log/meta": () => json(200, META),
      "GET /users": () => json(200, { items: [makeUser("manager")], total: 1 }),
      "GET /audit-log": (r) =>
        r.query.get("offset") === "0"
          ? json(200, { items: [entry()], total: 2 })
          : json(200, { items: [entry({ id: 2, user: null, action: "login", entity_label: null, entity_path: null, entity_id: null, entity_type: "client", location: null, changes: null })], total: 2 }),
    });
    open("/audit");
    expect(await screen.findByRole("link", { name: "ЗН-0001" })).toHaveAttribute("href", "/orders/o1");
    expect(screen.getByText("Изменение", { selector: "span" })).toBeInTheDocument();
    // 21:30 UTC = 00:30 следующего дня в Москве
    expect(screen.getByText(/11\.11\.2026, 00:30:00/)).toBeInTheDocument();
    expect(formatAuditTime("2026-11-10T21:30:00Z", "Europe/Moscow")).toContain("00:30");

    await user.click(screen.getByRole("button", { name: "Показать подробности" }));
    const diff = screen.getByLabelText("стало").closest("dd");
    expect(diff?.textContent?.replace(/\s+/g, " ").trim()).toBe("new in_progress");
    expect(screen.getByText("***")).toBeInTheDocument();
    expect(screen.getByText(/IP: 10\.0\.0\.1/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Показать ещё" }));
    expect(await screen.findByText("Система", { selector: "span" })).toBeInTheDocument();
    expect(calls(f, "GET /audit-log")).toHaveLength(2);
  });

  it("фильтры идут в URL и запрос; пусто — «Сбросить фильтры»; ошибка 422 по полю", async () => {
    const user = userEvent.setup();
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /audit-log/meta": () => json(200, META),
      "GET /users": () => json(200, { items: [], total: 0 }),
      "GET /audit-log": (r) => (r.query.get("date_to") ? apiError(422, "validation_error", { date_to: "out_of_range" }) : json(200, { items: [], total: 0 })),
    });
    open("/audit?action=login");
    expect(await screen.findByText("Записей по выбранным фильтрам нет")).toBeInTheDocument();
    expect(calls(f, "GET /audit-log")[0][0]).toContain("action=login");
    fireEvent.change(screen.getByLabelText("По дату"), { target: { value: "2026-01-01" } });
    expect(await screen.findByText(/не более 366 суток/)).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Сбросить фильтры" })[0]);
    await waitFor(() => expect(window.location.search).toBe(""));
  });
});

describe("системные настройки D-09", () => {
  it("проверка формы: возрастание порогов и диапазоны", () => {
    const form = { discount: "20,5", summaryOff: false, summaryTime: "21:00", retention: "30", hours: ["2", "5", "8"], actions: ["5", "15", "30"] };
    expect(validate(form).errors).toEqual({});
    expect(validate(form).values.discount_alert_percent).toBe("20.50");
    expect(validate({ ...form, hours: ["2", "2", "8"] }).errors.heatmap_hours).toBeTruthy();
    expect(validate({ ...form, hours: ["0.3", "5", "8"] }).errors.heatmap_hours).toBeTruthy();
    expect(validate({ ...form, retention: "3" }).errors.session_retention_days).toBeTruthy();
    expect(validate({ ...form, summaryOff: true }).values.daily_summary_time).toBeNull();
  });

  it("сохранение отправляет только изменённые ключи, кнопка активна при изменениях", async () => {
    const user = userEvent.setup();
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /settings": () => json(200, SETTINGS),
      "PATCH /settings": (r) => json(200, { ...SETTINGS, ...(r.body as object), updated_at: "2026-11-10T10:00:00Z", updated_by: { id: "u", full_name: "Иван director" } }),
    });
    open("/system-settings");
    const save = await screen.findByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    const input = screen.getByLabelText(/Порог скидки/);
    await user.clear(input);
    await user.type(input, "25");
    expect(save).toBeEnabled();
    await user.click(save);
    expect(await screen.findByText("Настройки сохранены")).toBeInTheDocument();
    expect(calls(f, "PATCH /settings")[0][1]?.body).toBe(JSON.stringify({ discount_alert_percent: "25.00" }));
    expect(screen.getByRole("link", { name: "Категории расходов" })).toBeInTheDocument();
  });

  it("422 от сервера по ключу показывается у поля", async () => {
    const user = userEvent.setup();
    mockApi({
      ...base(makeUser("director")),
      "GET /settings": () => json(200, SETTINGS),
      "PATCH /settings": () => apiError(422, "validation_error", { session_retention_days: "out_of_range" }),
    });
    open("/system-settings");
    const days = await screen.findByLabelText(/Срок хранения/);
    await user.clear(days);
    await user.type(days, "60");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText(/от 7 до 365 дней/, { selector: "span" })).toBeInTheDocument();
  });
});

describe("сессии C-02 и D-05", () => {
  const S = (o: Partial<UserSession> = {}): UserSession => ({ id: "s1", created_at: "2026-11-01T10:00:00Z", last_active_at: "2026-11-09T10:00:00Z", ip: "1.2.3.4", user_agent: "UA", device: "Chrome · Windows", is_current: true, ...o });

  it("список, метка «Это устройство», завершение с подтверждением и «Завершить все остальные»", async () => {
    const user = userEvent.setup();
    let list = [S(), S({ id: "s2", device: "Safari · iPhone", is_current: false })];
    const f = mockApi({
      ...base(makeUser("mechanic")),
      "GET /auth/sessions": () => json(200, list),
      "DELETE /auth/sessions/s2": () => {
        list = [list[0]];
        return json(204);
      },
      "POST /auth/sessions/revoke-others": () => json(204),
    });
    open("/settings");
    expect(await screen.findByText("Safari · iPhone")).toBeInTheDocument();
    expect(screen.getByText("Это устройство")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Завершить" }));
    const dlg = await screen.findByRole("dialog", { name: "Завершить сессию?" });
    await user.click(within(dlg).getByRole("button", { name: "Завершить" }));
    expect(await screen.findByText("Других активных сессий нет")).toBeInTheDocument();
    expect(calls(f, "DELETE /auth/sessions/s2")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Завершить все остальные" })).toBeNull();
  });

  it("D-05: «Последний вход» и «Завершить все сессии»", async () => {
    const user = userEvent.setup();
    const emp = makeUser("manager", { id: "u9", last_login_at: "2026-11-09T10:00:00Z" });
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /users/u9": () => json(200, emp),
      "POST /users/u9/revoke-sessions": () => json(204),
    });
    open("/users/u9");
    expect(await screen.findByText(/Последний вход: 09\.11\.2026/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Завершить все сессии" }));
    expect(await screen.findByText("Сессии сотрудника завершены")).toBeInTheDocument();
    expect(calls(f, "POST /users/u9/revoke-sessions")).toHaveLength(1);
  });
});
