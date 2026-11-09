import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { ERROR_MESSAGES } from "@/shared/api/errors";
import type { Role, User } from "@/shared/api/types";

import { type Handler, LOC1, LOC2, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const noSession: Handler = () => apiError(401, "invalid_token");
const base = (user: User | null): Record<string, Handler> => ({
  "POST /auth/refresh": user ? () => json(200, session(user)) : noSession,
  "GET /locations": () => json(200, user?.role === "director" ? [LOC1, LOC2] : [LOC1]),
  "POST /auth/logout": () => json(204),
});

function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.unstubAllGlobals());

describe("вход", () => {
  async function fillAndSubmit(login: string, password: string) {
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Логин"), login);
    await u.type(screen.getByLabelText("Пароль"), password);
    await u.click(screen.getByRole("button", { name: "Войти" }));
    return u;
  }

  it("успех: сразу рабочий стол роли, токен не в localStorage", async () => {
    const director = makeUser("director");
    const f = mockApi({ ...base(null), "POST /auth/login": () => json(200, session(director, "SECRET-TOKEN")) });
    open("/login");
    await fillAndSubmit("director", "demo-password-123");
    expect(await screen.findByText("Рабочий стол руководителя")).toBeInTheDocument();
    expect(calls(f, "POST /auth/login")).toHaveLength(1);
    expect(JSON.stringify(localStorage)).not.toContain("SECRET-TOKEN");
    expect(JSON.stringify(sessionStorage)).not.toContain("SECRET-TOKEN");
    expect(window.location.pathname).toBe("/");
  });

  it("неверный пароль: сообщение из словаря, текст сервера не показывается", async () => {
    mockApi({ ...base(null), "POST /auth/login": () => apiError(401, "invalid_credentials") });
    open("/login");
    await fillAndSubmit("director", "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(ERROR_MESSAGES.invalid_credentials);
    expect(document.body.textContent).not.toContain("SQLSTATE");
    expect(screen.getByRole("button", { name: "Войти" })).toBeEnabled();
  });

  it("блокировка после неудач (423)", async () => {
    mockApi({ ...base(null), "POST /auth/login": () => apiError(423, "account_locked") });
    open("/login");
    await fillAndSubmit("director", "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent(ERROR_MESSAGES.account_locked);
  });

  it("лимит запросов (429) с Retry-After", async () => {
    mockApi({ ...base(null), "POST /auth/login": () => apiError(429, "rate_limited", {}, { "Retry-After": "30" }) });
    open("/login");
    await fillAndSubmit("director", "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent("Повторите через 30 с");
  });

  it("неавторизованный на защищённом URL → вход, затем возврат на тот же адрес", async () => {
    const director = makeUser("director");
    mockApi({
      ...base(null),
      "POST /auth/login": () => json(200, session(director)),
      "GET /users": () => json(200, { items: [], total: 0 }),
    });
    open("/users");
    await fillAndSubmit("director", "demo-password-123");
    expect(await screen.findByRole("heading", { name: "Сотрудники" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/users");
  });

  it("выход возвращает на экран входа", async () => {
    const f = mockApi(base(makeUser("manager")));
    open("/");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Выйти" }));
    expect(await screen.findByRole("button", { name: "Войти" })).toBeInTheDocument();
    expect(calls(f, "POST /auth/logout")).toHaveLength(1);
  });
});

describe("авто-refresh", () => {
  const director = makeUser("director");

  it("401 → один общий refresh для параллельных запросов и повтор с новым токеном", async () => {
    let refreshes = 0;
    const f = mockApi({
      "POST /auth/refresh": () => json(200, session(director, `tok${++refreshes}`)),
      "GET /locations": (r) => (r.auth === "Bearer tok2" ? json(200, [LOC1, LOC2]) : apiError(401, "unauthorized")),
      "GET /users": (r) =>
        r.auth === "Bearer tok2"
          ? json(200, { items: [makeUser("manager", { full_name: "Пётр Менеджеров" })], total: 1 })
          : apiError(401, "unauthorized"),
    });
    open("/users");
    expect((await screen.findAllByText("Пётр Менеджеров")).length).toBeGreaterThan(0);
    // bootstrap + один refresh на оба параллельных 401
    expect(calls(f, "POST /auth/refresh")).toHaveLength(2);
  });

  it("refresh не удался → экран входа с сообщением «Сессия истекла»", async () => {
    let n = 0;
    mockApi({
      "POST /auth/refresh": () => (n++ === 0 ? json(200, session(director)) : apiError(401, "invalid_token")),
      "GET /locations": () => json(200, [LOC1]),
      "GET /users": () => apiError(401, "unauthorized"),
    });
    open("/users");
    expect(await screen.findByText("Сессия истекла, войдите снова")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Войти" })).toBeInTheDocument();
  });
});

describe("защищённые маршруты по ролям", () => {
  it.each<[Role, string]>([
    ["mechanic", "Мои задачи"], // M-01: у механика рабочий стол — список задач
    ["manager", "Рабочий стол менеджера"],
    ["director", "Рабочий стол руководителя"],
  ])("%s видит свой рабочий стол", async (role, title) => {
    mockApi(base(makeUser(role)));
    open("/");
    expect(await screen.findByText(title)).toBeInTheDocument();
  });

  it("менеджер не видит «Сотрудники» и не открывает по прямому URL", async () => {
    const f = mockApi({ ...base(makeUser("manager")), "GET /users": () => json(200, { items: [], total: 0 }) });
    open("/users");
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Сотрудники" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Точки" })).toBeNull();
    expect(calls(f, "GET /users")).toHaveLength(0);
  });

  it("менеджер не открывает карточку точки и создание сотрудника", async () => {
    mockApi(base(makeUser("manager")));
    open("/locations/new");
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
  });

  it("руководитель видит «Сотрудники» и «Точки» и переключатель «Все точки»", async () => {
    mockApi(base(makeUser("director")));
    open("/");
    expect((await screen.findAllByRole("link", { name: "Сотрудники" })).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Точки" }).length).toBeGreaterThan(0);
    const sel = await screen.findByRole("combobox", { name: "Точка" });
    expect(within(sel).getByRole("option", { name: "Все точки" })).toBeInTheDocument();
  });
});

describe("сотрудники", () => {
  it("<script> в ФИО выводится как текст и не создаёт элементов", async () => {
    const evil = '<script>alert(1)</script><img src=x onerror=alert(2)>';
    mockApi({
      ...base(makeUser("director")),
      "GET /users": () => json(200, { items: [makeUser("manager", { full_name: evil })], total: 1 }),
    });
    const { container } = open("/users");
    expect((await screen.findAllByText(evil)).length).toBeGreaterThan(0);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("поиск и фильтры уходят в query-параметры", async () => {
    const f = mockApi({ ...base(makeUser("director")), "GET /users": () => json(200, { items: [], total: 0 }) });
    open("/users");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Поиск"), "иван");
    await u.selectOptions(screen.getByLabelText("Роль"), "mechanic");
    await waitFor(() => {
      const last = f.mock.calls.filter(([i]) => String(i).startsWith("/api/v1/users?")).at(-1)?.[0] as string;
      expect(last).toContain("search=%D0%B8%D0%B2%D0%B0%D0%BD");
      expect(last).toContain("role=mechanic");
    });
  });

  it("создание: дубль логина → ошибка у поля", async () => {
    mockApi({
      ...base(makeUser("director")),
      "POST /users": () => apiError(409, "unique_violation"),
    });
    open("/users/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Логин"), "manager1");
    await u.type(screen.getByLabelText("ФИО"), "Пётр");
    await u.type(screen.getByLabelText("Начальный пароль"), "long-password-1");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    expect(await screen.findByText("Такой логин уже занят")).toBeInTheDocument();
  });

  it("создание: отправляет данные по контракту и открывает карточку", async () => {
    const created = makeUser("manager", { id: "new-id", login: "manager1", full_name: "Пётр" });
    const f = mockApi({
      ...base(makeUser("director")),
      "POST /users": () => json(201, created),
      "GET /users/new-id": () => json(200, created),
    });
    open("/users/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Логин"), "manager1");
    await u.type(screen.getByLabelText("ФИО"), "Пётр");
    await u.type(screen.getByLabelText("Начальный пароль"), "long-password-1");
    await u.click(await screen.findByLabelText("Москва-1"));
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(window.location.pathname).toBe("/users/new-id"));
    expect(JSON.parse(String(calls(f, "POST /users")[0][1]?.body))).toEqual({
      login: "manager1",
      full_name: "Пётр",
      role: "manager",
      password: "long-password-1",
      location_ids: ["l1"],
    });
  });

  it("создание: единственная точка отмечена сразу и уходит в location_ids", async () => {
    const created = makeUser("mechanic", { id: "new-id", login: "mech2", full_name: "Пётр" });
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /locations": () => json(200, [LOC1]),
      "POST /users": () => json(201, created),
      "GET /users/new-id": () => json(200, created),
    });
    open("/users/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Логин"), "mech2");
    await u.type(screen.getByLabelText("ФИО"), "Пётр");
    await u.type(screen.getByLabelText("Начальный пароль"), "long-password-1");
    await waitFor(() => expect(screen.getByLabelText("Москва-1")).toBeChecked());
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(window.location.pathname).toBe("/users/new-id"));
    expect(JSON.parse(String(calls(f, "POST /users")[0][1]?.body)).location_ids).toEqual(["l1"]);
  });

  it("блокировка с подтверждением отправляет is_active=false", async () => {
    const target = makeUser("mechanic", { id: "m1", full_name: "Сидор" });
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /users/m1": () => json(200, target),
      "PATCH /users/m1": () => json(200, { ...target, is_active: false }),
    });
    open("/users/m1");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Заблокировать" }));
    const dlg = await screen.findByRole("dialog");
    await u.click(within(dlg).getByRole("button", { name: "Заблокировать" }));
    await waitFor(() => expect(calls(f, "PATCH /users/m1")).toHaveLength(1));
    expect(JSON.parse(String(calls(f, "PATCH /users/m1")[0][1]?.body))).toEqual({ is_active: false });
  });

  it("сброс пароля отправляет new_password", async () => {
    const target = makeUser("mechanic", { id: "m1" });
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /users/m1": () => json(200, target),
      "POST /users/m1/reset-password": () => json(204),
    });
    open("/users/m1");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Сбросить пароль" }));
    const dlg = await screen.findByRole("dialog");
    await u.type(within(dlg).getByLabelText("Новый пароль"), "another-pass-123");
    await u.click(within(dlg).getByRole("button", { name: "Сбросить" }));
    await waitFor(() => expect(calls(f, "POST /users/m1/reset-password")).toHaveLength(1));
    expect(JSON.parse(String(calls(f, "POST /users/m1/reset-password")[0][1]?.body))).toEqual({ new_password: "another-pass-123" });
  });
});

describe("точки", () => {
  it("создание точки без телефона не шлёт phone", async () => {
    const created = { ...LOC1, id: "l9", name: "Новая" };
    const f = mockApi({
      ...base(makeUser("director")),
      "POST /locations": () => json(201, created),
      "GET /locations/l9": () => json(200, created),
    });
    open("/locations/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Название"), "Новая");
    await u.type(screen.getByLabelText("Адрес"), "ул. Новая, 5");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(window.location.pathname).toBe("/locations/l9"));
    expect(JSON.parse(String(calls(f, "POST /locations")[0][1]?.body))).toEqual({ name: "Новая", address: "ул. Новая, 5" });
  });

  it("список точек", async () => {
    mockApi(base(makeUser("director")));
    open("/locations");
    expect((await screen.findAllByText("Москва-2")).length).toBeGreaterThan(0);
  });
});

describe("смена пароля", () => {
  async function openSettings(handler: Handler) {
    const f = mockApi({ ...base(makeUser("manager")), "POST /auth/change-password": handler });
    open("/settings");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Текущий пароль"), "old-password-1");
    return { f, u };
  }

  it("успех: запрос по контракту, toast, поля очищены", async () => {
    const { f, u } = await openSettings(() => json(204));
    await u.type(screen.getByLabelText("Новый пароль"), "brand-new-pass-1");
    await u.type(screen.getByLabelText("Повторите новый пароль"), "brand-new-pass-1");
    await u.click(screen.getByRole("button", { name: "Сменить пароль" }));
    expect(await screen.findByText("Пароль изменён")).toBeInTheDocument();
    expect(JSON.parse(String(calls(f, "POST /auth/change-password")[0][1]?.body))).toEqual({
      current_password: "old-password-1",
      new_password: "brand-new-pass-1",
    });
    expect(screen.getByLabelText("Текущий пароль")).toHaveValue("");
  });

  it("повтор не совпадает → ошибка без запроса", async () => {
    const { f, u } = await openSettings(() => json(204));
    await u.type(screen.getByLabelText("Новый пароль"), "brand-new-pass-1");
    await u.type(screen.getByLabelText("Повторите новый пароль"), "different-pass-1");
    await u.click(screen.getByRole("button", { name: "Сменить пароль" }));
    expect(await screen.findByText("Пароли не совпадают")).toBeInTheDocument();
    expect(calls(f, "POST /auth/change-password")).toHaveLength(0);
  });

  it("неверный текущий пароль (400) → ошибка у поля", async () => {
    const { u } = await openSettings(() => apiError(400, "invalid_current_password"));
    await u.type(screen.getByLabelText("Новый пароль"), "brand-new-pass-1");
    await u.type(screen.getByLabelText("Повторите новый пароль"), "brand-new-pass-1");
    await u.click(screen.getByRole("button", { name: "Сменить пароль" }));
    expect(await screen.findByText(ERROR_MESSAGES.invalid_current_password)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SQLSTATE");
  });

  it("слабый пароль (422 fields.new_password) → подсказка у поля, текст сервера не показывается", async () => {
    const { u } = await openSettings(() => apiError(422, "validation_error", { new_password: "Пароль слишком простой SERVER-RAW" }));
    await u.type(screen.getByLabelText("Новый пароль"), "short");
    await u.type(screen.getByLabelText("Повторите новый пароль"), "short");
    await u.click(screen.getByRole("button", { name: "Сменить пароль" }));
    expect(await screen.findByText(/Пароль слишком простой: не короче 10/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SERVER-RAW");
  });
});
