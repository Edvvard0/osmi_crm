import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { ERROR_MESSAGES } from "@/shared/api/errors";
import type { Client, ClientDetail, Role, SearchHit, User, Vehicle, VehicleDetail } from "@/shared/api/types";
import { isValidVin, maskPhone, normalizePhone, normalizePlate } from "@/shared/lib/masks";

import { type Handler, LOC1, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const base = (user: User): Record<string, Handler> => ({
  "POST /auth/refresh": () => json(200, session(user)),
  "GET /locations": () => json(200, [LOC1]),
});

function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

const client = (over: Partial<Client> = {}): Client => ({
  id: "c1",
  client_type: "person",
  full_name: "Анна Петрова",
  company_name: null,
  inn: null,
  phone: "+79991234567",
  phone_extra: null,
  email: null,
  source: "referral",
  discount_percent: 5,
  notes: null,
  vehicles_count: 0,
  created_at: "2026-01-01T00:00:00Z",
  archived_at: null,
  ...over,
});
const vehicle = (over: Partial<Vehicle> = {}): Vehicle => ({
  id: "v1",
  client_id: "c1",
  make: "Toyota",
  model: "Camry",
  year: 2018,
  vin: null,
  plate_number: "А123ВС777",
  color: null,
  mileage: null,
  notes: null,
  created_at: "2026-01-01T00:00:00Z",
  archived_at: null,
  ...over,
});
const detail = (c: Client, vehicles: Vehicle[] = []): ClientDetail => ({ ...c, vehicles });

const manager = () => makeUser("manager");
const lastUrl = (f: ReturnType<typeof mockApi>, prefix: string) =>
  f.mock.calls.filter(([i]) => String(i).startsWith(prefix)).at(-1)?.[0] as string;

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.unstubAllGlobals());

describe("маски и валидаторы", () => {
  it("телефон: любой формат → +7…", () => {
    expect(normalizePhone("8 (999) 123-45-67")).toBe("+79991234567");
    expect(normalizePhone("+7 999 123 45 67")).toBe("+79991234567");
    expect(normalizePhone("9991234567")).toBe("+79991234567");
    expect(normalizePhone("8999")).toBeNull();
    expect(maskPhone("89991234567")).toBe("+7 (999) 123-45-67");
    expect(maskPhone("")).toBe("");
  });
  it("госномер: верхний регистр, латиница → кириллица", () => {
    expect(normalizePlate("a123bc 77")).toBe("А123ВС77");
    expect(normalizePlate("х-001-хх")).toBe("Х001ХХ");
  });
  it("VIN: 17 символов без I, O, Q", () => {
    expect(isValidVin("1HGCM82633A004352")).toBe(true);
    expect(isValidVin("1HGCM82633A00435")).toBe(false);
    expect(isValidVin("1HGCM82633A00435I")).toBe(false);
    expect(isValidVin("1HGCM82633A00435O")).toBe(false);
    expect(isValidVin("1HGCM82633A00435Q")).toBe(false);
  });
});

describe("права", () => {
  it("механик: нет пункта «Клиенты» и нет доступа по прямому URL, запросов нет", async () => {
    const f = mockApi({ ...base(makeUser("mechanic")), "GET /clients": () => json(200, { items: [], total: 0 }) });
    open("/clients");
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Клиенты" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Глобальный поиск" })).toBeNull();
    expect(calls(f, "GET /clients")).toHaveLength(0);
  });

  it.each<Role>(["manager", "director"])("%s видит «Клиенты» в навигации", async (role) => {
    mockApi(base(makeUser(role)));
    open("/");
    expect((await screen.findAllByRole("link", { name: "Клиенты" })).length).toBeGreaterThan(0);
  });
});

describe("список клиентов", () => {
  it("пустое состояние со ссылкой на создание", async () => {
    mockApi({ ...base(manager()), "GET /clients": () => json(200, { items: [], total: 0 }) });
    open("/clients");
    expect(await screen.findByText("Клиентов пока нет")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "+ Новый клиент" }).length).toBeGreaterThan(0);
  });

  it("отображает клиентов и отправляет фильтры по контракту", async () => {
    const f = mockApi({ ...base(manager()), "GET /clients": () => json(200, { items: [client({ vehicles_count: 2 })], total: 1 }) });
    open("/clients");
    expect((await screen.findAllByText("Анна Петрова")).length).toBeGreaterThan(0);
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText("Тип"), "company");
    await u.selectOptions(screen.getByLabelText("Источник"), "ads");
    await u.selectOptions(screen.getByLabelText("Архив"), "true");
    await waitFor(() => {
      const url = lastUrl(f, "/api/v1/clients?");
      expect(url).toContain("client_type=company");
      expect(url).toContain("source=ads");
      expect(url).toContain("archived=true");
      expect(url).toContain("limit=50");
    });
  });

  it("поиск с задержкой; спецсимволы %, _, ' уходят как есть (URL-кодированные)", async () => {
    const f = mockApi({ ...base(manager()), "GET /clients": () => json(200, { items: [], total: 0 }) });
    open("/clients");
    const u = userEvent.setup();
    const input = await screen.findByLabelText("Поиск");
    await waitFor(() => expect(calls(f, "GET /clients")).toHaveLength(1));
    await u.type(input, "%_'");
    // сразу после ввода нового запроса ещё нет (debounce 300 мс)
    expect(calls(f, "GET /clients")).toHaveLength(1);
    await waitFor(() => expect(calls(f, "GET /clients")).toHaveLength(2), { timeout: 2000 });
    const url = lastUrl(f, "/api/v1/clients?");
    expect(url).toContain("search=%25_%27");
    expect(new URL(url, "http://x").searchParams.get("search")).toBe("%_'");
  });

  it("<script> в ФИО, названии компании и заметках выводится как текст", async () => {
    const evil = "<script>alert(1)</script><img src=x onerror=alert(2)>";
    mockApi({
      ...base(manager()),
      "GET /clients": () => json(200, { items: [client({ full_name: evil, company_name: evil })], total: 1 }),
      "GET /clients/c1": () => json(200, detail(client({ full_name: evil, notes: evil }), [vehicle({ make: evil })])),
    });
    const { container } = open("/clients");
    expect((await screen.findAllByText(evil)).length).toBeGreaterThan(0);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    window.history.pushState({}, "", "/clients/c1");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect((await screen.findAllByText(evil, { exact: false })).length).toBeGreaterThan(0);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("форма клиента", () => {
  async function fillClient(u: ReturnType<typeof userEvent.setup>, phone = "89991234567") {
    await u.type(await screen.findByLabelText("ФИО"), "Анна Петрова");
    await u.type(screen.getByLabelText("Телефон"), phone);
  }

  it("маска телефона и нормализация к +7 в запросе", async () => {
    const f = mockApi({
      ...base(manager()),
      "POST /clients": () => json(201, client()),
      "GET /clients/c1": () => json(200, detail(client())),
    });
    open("/clients/new");
    const u = userEvent.setup();
    await fillClient(u);
    expect(screen.getByLabelText("Телефон")).toHaveValue("+7 (999) 123-45-67");
    await u.selectOptions(screen.getByLabelText("Источник"), "referral");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(window.location.pathname).toBe("/clients/c1"));
    expect(JSON.parse(String(calls(f, "POST /clients")[0][1]?.body))).toEqual({
      client_type: "person",
      full_name: "Анна Петрова",
      company_name: null,
      inn: null,
      phone: "+79991234567",
      phone_extra: null,
      email: null,
      source: "referral",
      discount_percent: 0,
      notes: null,
    });
  });

  it("валидация: пустые поля, неполный телефон, ИНН, скидка — запрос не уходит", async () => {
    const f = mockApi(base(manager()));
    open("/clients/new");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Создать" }));
    expect(screen.getAllByText("Обязательное поле").length).toBe(2);
    await u.type(screen.getByLabelText(/^Телефон/), "999");
    await u.selectOptions(screen.getByLabelText("Тип клиента"), "company");
    await u.type(screen.getByLabelText(/^ИНН/), "12345");
    const d = screen.getByLabelText(/^Скидка/);
    await u.clear(d);
    await u.type(d, "101");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    expect(screen.getByText("ИНН: 10 или 12 цифр")).toBeInTheDocument();
    expect(screen.getByText("Скидка: число от 0 до 100")).toBeInTheDocument();
    expect(screen.getByText(/Введите номер полностью/)).toBeInTheDocument();
    expect(calls(f, "POST /clients")).toHaveLength(0);
  });

  it("компания: название и ИНН 10 цифр уходят в запрос", async () => {
    const f = mockApi({
      ...base(manager()),
      "POST /clients": () => json(201, client({ id: "c2", client_type: "company" })),
      "GET /clients/c2": () => json(200, detail(client({ id: "c2" }))),
    });
    open("/clients/new");
    const u = userEvent.setup();
    await u.selectOptions(await screen.findByLabelText("Тип клиента"), "company");
    await u.type(screen.getByLabelText("Контактное лицо"), "Олег");
    await u.type(screen.getByLabelText("Название компании"), "ООО Ромашка");
    await u.type(screen.getByLabelText("ИНН"), "7707083893");
    await u.type(screen.getByLabelText("Телефон"), "+7 999 000 11 22");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(window.location.pathname).toBe("/clients/c2"));
    const body = JSON.parse(String(calls(f, "POST /clients")[0][1]?.body));
    expect(body).toMatchObject({ client_type: "company", company_name: "ООО Ромашка", inn: "7707083893", phone: "+79990001122" });
  });

  it("дубль телефона: сообщение из словаря и ссылка на существующего клиента", async () => {
    const f = mockApi({
      ...base(manager()),
      "POST /clients": () =>
        json(409, { error: { code: "duplicate_phone", message: "SERVER TEXT SQLSTATE", details: { existing_id: "c9", existing_name: "Иван Старый" } } }),
    });
    open("/clients/new");
    const u = userEvent.setup();
    await fillClient(u);
    await u.click(screen.getByRole("button", { name: "Создать" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(ERROR_MESSAGES.duplicate_phone);
    expect(document.body.textContent).not.toContain("SQLSTATE");
    const link = within(alert).getByRole("link", { name: "Иван Старый" });
    expect(link).toHaveAttribute("href", "/clients/c9");
    expect(calls(f, "POST /clients")).toHaveLength(1);
  });
});

describe("карточка клиента и автомобили", () => {
  it("создание клиента с двумя авто (E2E)", async () => {
    let cars: Vehicle[] = [];
    const f = mockApi({
      ...base(manager()),
      "POST /clients": () => json(201, client()),
      "GET /clients/c1": () => json(200, detail(client({ vehicles_count: cars.length }), cars)),
      "POST /clients/c1/vehicles": (r) => {
        const b = r.body as Partial<Vehicle>;
        const v = vehicle({ id: `v${cars.length + 1}`, make: b.make!, model: b.model!, vin: b.vin ?? null, plate_number: b.plate_number ?? null });
        cars = [...cars, v];
        return json(201, v);
      },
    });
    open("/clients/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("ФИО"), "Анна Петрова");
    await u.type(screen.getByLabelText("Телефон"), "89991234567");
    await u.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => expect(window.location.pathname).toBe("/clients/c1"));
    expect(await screen.findByText("История заказов появится позже")).toBeInTheDocument();
    expect(screen.getByText("Автомобилей пока нет")).toBeInTheDocument();

    for (const [make, model, plate, vin] of [
      ["Toyota", "Camry", "a123bc777", "1hgcm82633a004352"],
      ["Kia", "Rio", "e555kx77", ""],
    ]) {
      await u.click(await screen.findByRole("link", { name: "+ Добавить авто" }));
      await u.type(await screen.findByLabelText("Марка"), make);
      await u.type(screen.getByLabelText("Модель"), model);
      await u.type(screen.getByLabelText("Госномер"), plate);
      if (vin) await u.type(screen.getByLabelText("VIN"), vin);
      await u.click(screen.getByRole("button", { name: "Добавить" }));
      await waitFor(() => expect(window.location.pathname).toBe("/clients/c1"));
    }
    expect(await screen.findByText("Toyota Camry")).toBeInTheDocument();
    expect(await screen.findByText("Kia Rio")).toBeInTheDocument();
    const bodies = calls(f, "POST /clients/c1/vehicles").map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toMatchObject({ make: "Toyota", model: "Camry", plate_number: "А123ВС777", vin: "1HGCM82633A004352" });
    expect(bodies[1]).toMatchObject({ plate_number: "Е555КХ77", vin: null });
  });

  it("карточка: контакты, источник, скидка, заметки, архивирование", async () => {
    const c = client({ email: "a@b.ru", notes: "Любит кофе", discount_percent: 7 });
    const f = mockApi({
      ...base(manager()),
      "GET /clients/c1": () => json(200, detail(c, [vehicle()])),
      "POST /clients/c1/archive": () => json(200, { ...c, archived_at: "2026-02-01T00:00:00Z" }),
    });
    open("/clients/c1");
    expect(await screen.findByText("+79991234567")).toBeInTheDocument();
    expect(screen.getByText("Рекомендация")).toBeInTheDocument();
    expect(screen.getByText("7%")).toBeInTheDocument();
    expect(screen.getByText("Любит кофе")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Toyota Camry" })).toHaveAttribute("href", "/vehicles/v1");
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Архивировать" }));
    const dlg = await screen.findByRole("dialog", { name: "Архивировать клиента?" });
    await u.click(within(dlg).getByRole("button", { name: "Архивировать" }));
    await waitFor(() => expect(calls(f, "POST /clients/c1/archive")).toHaveLength(1));
  });

  it("архивный клиент: кнопка «Восстановить»", async () => {
    const c = client({ archived_at: "2026-02-01T00:00:00Z" });
    const f = mockApi({
      ...base(manager()),
      "GET /clients/c1": () => json(200, detail(c)),
      "POST /clients/c1/restore": () => json(200, { ...c, archived_at: null }),
    });
    open("/clients/c1");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Восстановить" }));
    await waitFor(() => expect(calls(f, "POST /clients/c1/restore")).toHaveLength(1));
  });

  it("форма авто: VIN короче 17 и с I/O/Q не отправляется", async () => {
    const f = mockApi(base(manager()));
    open("/clients/c1/vehicles/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Марка"), "Kia");
    await u.type(screen.getByLabelText("Модель"), "Rio");
    await u.type(screen.getByLabelText("VIN"), "1hgcm82633a00435");
    await u.click(screen.getByRole("button", { name: "Добавить" }));
    expect(screen.getByText("VIN: 17 символов, без букв I, O, Q")).toBeInTheDocument();
    await u.type(screen.getByLabelText(/^VIN/), "q");
    await u.click(screen.getByRole("button", { name: "Добавить" }));
    expect(screen.getByText("VIN: 17 символов, без букв I, O, Q")).toBeInTheDocument();
    expect(calls(f, "POST /clients/c1/vehicles")).toHaveLength(0);
  });

  it("маска госномера: верхний регистр и кириллица", async () => {
    mockApi(base(manager()));
    open("/clients/c1/vehicles/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Госномер"), "a123bc77");
    expect(screen.getByLabelText("Госномер")).toHaveValue("А123ВС77");
  });

  it("дубль VIN: ссылка на существующий автомобиль", async () => {
    mockApi({
      ...base(manager()),
      "POST /clients/c1/vehicles": () =>
        json(409, { error: { code: "duplicate_vin", message: "SERVER TEXT SQLSTATE", details: { existing_vehicle_id: "v9", existing_client_id: "c7" } } }),
    });
    open("/clients/c1/vehicles/new");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Марка"), "Kia");
    await u.type(screen.getByLabelText("Модель"), "Rio");
    await u.type(screen.getByLabelText("VIN"), "1HGCM82633A004352");
    await u.click(screen.getByRole("button", { name: "Добавить" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(ERROR_MESSAGES.duplicate_vin);
    expect(document.body.textContent).not.toContain("SQLSTATE");
    expect(within(alert).getByRole("link")).toHaveAttribute("href", "/vehicles/v9");
  });

  it("карточка автомобиля: владелец, поля, архивирование", async () => {
    const v: VehicleDetail = { ...vehicle({ vin: "1HGCM82633A004352", mileage: 120000 }), client: { id: "c1", full_name: "Анна Петрова", phone: "+79991234567" } };
    const f = mockApi({
      ...base(manager()),
      "GET /vehicles/v1": () => json(200, v),
      "GET /clients/c1": () => json(200, detail(client())),
      "POST /vehicles/v1/archive": () => json(200, { ...v, archived_at: "2026-02-01T00:00:00Z" }),
    });
    open("/vehicles/v1");
    expect(await screen.findByRole("heading", { name: "Toyota Camry" })).toBeInTheDocument();
    expect(screen.getByText("1HGCM82633A004352")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Анна Петрова" })[0]).toHaveAttribute("href", "/clients/c1");
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Архивировать" }));
    const dlg = await screen.findByRole("dialog", { name: "Архивировать автомобиль?" });
    await u.click(within(dlg).getByRole("button", { name: "Архивировать" }));
    await waitFor(() => expect(calls(f, "POST /vehicles/v1/archive")).toHaveLength(1));
    await waitFor(() => expect(window.location.pathname).toBe("/clients/c1"));
  });
});

describe("глобальный поиск Ctrl+K", () => {
  const hits: SearchHit[] = [
    { type: "client", id: "c1", title: "Анна Петрова", subtitle: "+79991234567", client_id: "c1" },
    { type: "vehicle", id: "v1", title: "Toyota Camry", subtitle: "А123ВС777", client_id: "c1" },
  ];

  it("открывается по Ctrl+K, ищет от 2 символов, стрелки + Enter ведут на карточку", async () => {
    const f = mockApi({
      ...base(manager()),
      "GET /clients": () => json(200, { items: [], total: 0 }),
      "GET /search": () => json(200, hits),
      "GET /vehicles/v1": () => json(200, { ...vehicle(), client: { id: "c1", full_name: "Анна Петрова", phone: "+79991234567" } }),
    });
    open("/clients");
    const u = userEvent.setup();
    await screen.findByText("Клиентов пока нет");
    await u.keyboard("{Control>}k{/Control}");
    const input = await screen.findByRole("combobox", { name: "Поиск клиентов и автомобилей" });
    expect(input).toHaveFocus();
    await u.type(input, "а");
    await new Promise((r) => setTimeout(r, 400));
    expect(calls(f, "GET /search")).toHaveLength(0);
    await u.type(input, "1'%");
    const list = await screen.findByRole("listbox", { name: "Результаты поиска" });
    await within(list).findByText("Toyota Camry");
    const url = lastUrl(f, "/api/v1/search?");
    expect(new URL(url, "http://x").searchParams.get("q")).toBe("а1'%");
    expect(url).toContain("limit=10");
    const opts = within(list).getAllByRole("option");
    expect(opts[0]).toHaveAttribute("aria-selected", "true");
    await u.keyboard("{ArrowDown}");
    expect(within(list).getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    await u.keyboard("{Enter}");
    await waitFor(() => expect(window.location.pathname).toBe("/vehicles/v1"));
    expect(screen.queryByRole("dialog", { name: "Глобальный поиск" })).toBeNull();
  });

  it("Esc закрывает; <script> в результатах — текст", async () => {
    const evil = "<script>alert(1)</script>";
    mockApi({
      ...base(manager()),
      "GET /search": () => json(200, [{ type: "client", id: "c1", title: evil, subtitle: evil, client_id: "c1" }]),
    });
    const { container } = open("/");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Глобальный поиск" }));
    await u.type(await screen.findByRole("combobox", { name: "Поиск клиентов и автомобилей" }), "ab");
    expect((await screen.findAllByText(evil)).length).toBeGreaterThan(0);
    expect(container.querySelector("script")).toBeNull();
    await u.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Глобальный поиск" })).toBeNull();
  });

  it("ошибка поиска: сообщение из словаря", async () => {
    mockApi({ ...base(manager()), "GET /search": () => apiError(500, "internal_error") });
    open("/");
    const u = userEvent.setup();
    await screen.findByRole("button", { name: "Глобальный поиск" });
    await u.keyboard("{Control>}k{/Control}");
    await u.type(await screen.findByRole("combobox", { name: "Поиск клиентов и автомобилей" }), "ab");
    expect(await screen.findByText(ERROR_MESSAGES.internal_error, undefined, { timeout: 8000 })).toBeInTheDocument();
  }, 15000);
});
