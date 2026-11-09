import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { ERROR_MESSAGES } from "@/shared/api/errors";
import type { Category, Part, Post, Role, Service, ServicePrice, User } from "@/shared/api/types";
import { formatHours, formatMoney, parseDecimal } from "@/shared/lib/money";

import { type Handler, LOC1, LOC2, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const base = (user: User, locs = [LOC1]): Record<string, Handler> => ({
  "POST /auth/refresh": () => json(200, session(user)),
  "GET /locations": () => json(200, locs),
});

function open(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

const cat = (o: Partial<Category> = {}): Category => ({ id: "c1", name: "ТО", department: "service", sort_order: 0, is_active: true, ...o });
const svc = (o: Partial<Service> = {}): Service => ({
  id: "s1",
  category_id: "c1",
  code: "TO-1",
  name: "Замена масла",
  description: null,
  department: "service",
  unit: "pcs",
  base_price: "1500.00",
  norm_hours: "1.50",
  duration_minutes: 60,
  is_active: true,
  price: "1500.00",
  ...o,
});
const part = (o: Partial<Part> = {}): Part => ({
  id: "p1",
  sku: "OIL-5W30",
  name: "Масло 5W-30",
  brand: "Castrol",
  barcode: null,
  unit: "l",
  department: "both",
  sale_price: "900.00",
  is_active: true,
  ...o,
});
const page = <T,>(items: T[]) => json(200, { items, total: items.length });

const NB = new RegExp(String.fromCharCode(160), "g");
const text = (s: string | null) => (s ?? "").replace(NB, " ");

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.unstubAllGlobals());

describe("деньги и часы", () => {
  it("форматирование: 1 500,00 ₽", () => {
    expect(text(formatMoney("1500.00"))).toBe("1 500,00 ₽");
    expect(text(formatMoney("1234567.8"))).toBe("1 234 567,80 ₽");
    expect(text(formatMoney("0.5"))).toBe("0,50 ₽");
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("abc")).toBe("—");
    expect(text(formatHours("1.5"))).toBe("1,50 ч");
    expect(formatHours(null)).toBe("—");
  });
  it("разбор ввода: запятая и точка, строка с двумя знаками", () => {
    expect(parseDecimal("1500")).toBe("1500.00");
    expect(parseDecimal("1500,5")).toBe("1500.50");
    expect(parseDecimal("1500.55")).toBe("1500.55");
    expect(parseDecimal("1 500,5")).toBe("1500.50");
    expect(parseDecimal("007,1")).toBe("7.10");
    expect(parseDecimal("0")).toBe("0.00");
    expect(parseDecimal("1,5", 2)).toBe("1.50");
  });
  it("разбор ввода: мусор отклоняется", () => {
    for (const bad of ["", "abc", "-1", "1.234", "1,2,3", "1.500,00", "1e5", ","]) expect(parseDecimal(bad)).toBeNull();
  });
});

describe("права", () => {
  it("механик: нет пункта меню и нет доступа по прямому URL, запросов нет", async () => {
    const f = mockApi({ ...base(makeUser("mechanic")), "GET /service-categories": () => json(200, []), "GET /services": () => page([]) });
    open("/catalog");
    expect(await screen.findByText("Нет доступа")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Каталог/ })).toBeNull();
    expect(calls(f, "GET /services")).toHaveLength(0);
    expect(calls(f, "GET /service-categories")).toHaveLength(0);
  });

  it.each<[Role, string]>([
    ["manager", "Каталог"],
    ["director", "Каталог и цены"],
  ])("%s видит пункт «%s»", async (role, label) => {
    mockApi(base(makeUser(role)));
    open("/");
    expect((await screen.findAllByRole("link", { name: label })).length).toBeGreaterThan(0);
  });

  it("менеджер: только «Услуги» и «Запчасти», без кнопок правки, запрос с location_id", async () => {
    const f = mockApi({
      ...base(makeUser("manager")),
      "GET /service-categories": () => json(200, [cat()]),
      "GET /services": () => page([svc({ price: "1200.00" })]),
      "GET /parts": () => page([part()]),
    });
    open("/catalog");
    expect((await screen.findAllByText("Замена масла")).length).toBeGreaterThan(0);
    expect(screen.getByRole("tab", { name: "Услуги" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Запчасти и материалы" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Цены по точкам" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Посты" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Услуга" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Категория" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Изменить/ })).toBeNull();
    // Эффективная цена точки, а не базовая.
    expect(screen.getAllByText((_, el) => el?.tagName === "SPAN" && text(el.textContent) === "1 200,00 ₽").length).toBeGreaterThan(0);
    expect(screen.queryByText((_, el) => text(el?.textContent ?? "") === "1 500,00 ₽")).toBeNull();
    const svcCalls = calls(f, "GET /services");
    expect(svcCalls.length).toBeGreaterThan(0);
    for (const [url] of svcCalls) expect(new URL(String(url), "http://x").searchParams.get("location_id")).toBe("l1");
    expect(calls(f, "GET /service-prices")).toHaveLength(0);

    const u = userEvent.setup();
    await u.click(screen.getByRole("tab", { name: "Запчасти и материалы" }));
    expect((await screen.findAllByText("Масло 5W-30")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "+ Позиция" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Изменить/ })).toBeNull();
  });

  it("менеджер другой точки видит цену своей точки: location_id берётся из шапки", async () => {
    const m = makeUser("manager", { location_ids: ["l2"] });
    const f = mockApi({
      ...base(m, [LOC2]),
      "GET /service-categories": () => json(200, [cat()]),
      "GET /services": () => page([svc()]),
    });
    open("/catalog");
    await screen.findAllByText("Замена масла");
    const url = String(calls(f, "GET /services").at(-1)?.[0]);
    expect(new URL(url, "http://x").searchParams.get("location_id")).toBe("l2");
  });

  it("руководитель: все четыре вкладки и кнопки правки", async () => {
    mockApi({
      ...base(makeUser("director"), [LOC1, LOC2]),
      "GET /service-categories": () => json(200, [cat(), cat({ id: "c2", name: "Полировка", department: "detailing" })]),
      "GET /services": () => page([svc()]),
    });
    open("/catalog");
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Услуга" })).toBeEnabled());
    for (const n of ["Услуги", "Цены по точкам", "Посты", "Запчасти и материалы"]) expect(screen.getByRole("tab", { name: n })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Категория" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Изменить категорию Полировка" })).toBeInTheDocument();
  });
});

describe("услуги: дерево, фильтр отдела, счётчики", () => {
  it("фильтр по отделу и категории уходит в запрос; счётчики по категориям", async () => {
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /service-categories": () => json(200, [cat(), cat({ id: "c2", name: "Полировка", department: "detailing" })]),
      "GET /services": () => page([svc(), svc({ id: "s2", code: "TO-2", name: "Замена фильтра" }), svc({ id: "s3", category_id: "c2", code: "P-1", name: "Полировка кузова", department: "detailing" })]),
    });
    open("/catalog");
    const tree = await screen.findByRole("complementary", { name: "Категории" });
    await waitFor(() => expect(within(screen.getByRole("button", { name: /^ТО/ })).getByText("2")).toBeInTheDocument());
    expect(within(screen.getByRole("button", { name: /^Полировка/ })).getByText("1")).toBeInTheDocument();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: /^Полировка/ }));
    await waitFor(() => expect(String(calls(f, "GET /services").at(-1)?.[0])).toContain("category_id=c2"));
    await u.selectOptions(within(tree).getByLabelText("Отдел"), "detailing");
    await waitFor(() => expect(String(calls(f, "GET /services").at(-1)?.[0])).toContain("department=detailing"));
  });
});

describe("E2E: категория → услуга → цена для точки → сброс", () => {
  it("руководитель создаёт категорию, услугу, задаёт и сбрасывает цену точки", async () => {
    const cats: Category[] = [];
    const services: Service[] = [];
    const prices: ServicePrice[] = [];
    const f = mockApi({
      ...base(makeUser("director"), [LOC1, LOC2]),
      "GET /service-categories": () => json(200, cats),
      "POST /service-categories": (r) => {
        const b = r.body as { name: string; department: Category["department"]; sort_order: number };
        const c = cat({ id: "c-new", name: b.name, department: b.department, sort_order: b.sort_order });
        cats.push(c);
        return json(201, c);
      },
      "GET /services": () => page(services),
      "POST /services": (r) => {
        const b = r.body as Omit<Service, "id" | "department" | "is_active" | "price">;
        const s = svc({ id: "s-new", ...b, price: b.base_price });
        services.push(s);
        return json(201, s);
      },
      "GET /service-prices": (r) => json(200, prices.filter((p) => p.location_id === r.query.get("location_id"))),
      "PUT /services/s-new/prices/l1": (r) => {
        const p: ServicePrice = { service_id: "s-new", location_id: "l1", price: (r.body as { price: string }).price, updated_at: "2026-01-01T00:00:00Z" };
        prices.splice(0, prices.length, p);
        return json(200, p);
      },
      "DELETE /services/s-new/prices/l1": () => {
        prices.splice(0, prices.length);
        return json(204);
      },
    });
    open("/catalog");
    const u = userEvent.setup();

    // Категория
    await u.click(await screen.findByRole("button", { name: "+ Категория" }));
    let dlg = within(screen.getByRole("dialog", { name: "Новая категория" }));
    await u.type(dlg.getByLabelText("Название"), "ТО");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("button", { name: /^ТО/ })).toBeInTheDocument();
    expect(calls(f, "POST /service-categories")[0][1]?.body).toBe(JSON.stringify({ name: "ТО", department: "service", sort_order: 0 }));

    // Услуга: цена с запятой уходит строкой с двумя знаками
    await u.click(screen.getByRole("button", { name: "+ Услуга" }));
    dlg = within(screen.getByRole("dialog", { name: "Новая услуга" }));
    await u.type(dlg.getByLabelText("Код"), "TO-1");
    await u.type(dlg.getByLabelText("Название"), "Замена масла");
    await u.type(dlg.getByLabelText("Базовая цена, ₽"), "1500,5");
    await u.type(dlg.getByLabelText("Нормочасы"), "1,5");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect((await screen.findAllByText("Замена масла")).length).toBeGreaterThan(0);
    const sent = JSON.parse(String(calls(f, "POST /services")[0][1]?.body)) as Record<string, unknown>;
    expect(sent).toMatchObject({ category_id: "c-new", code: "TO-1", name: "Замена масла", base_price: "1500.50", norm_hours: "1.50", duration_minutes: 60, unit: "pcs" });

    // Цена для точки
    await u.click(screen.getByRole("tab", { name: "Цены по точкам" }));
    const cellL1 = await screen.findByRole("button", { name: /Замена масла, Москва-1: 1.500,50.₽ \(базовая\)/ });
    await u.click(cellL1);
    dlg = within(screen.getByRole("dialog", { name: "Цена: Замена масла" }));
    expect(dlg.queryByRole("button", { name: "Сбросить к базовой" })).toBeNull();
    const input = dlg.getByLabelText("Цена на точке, ₽");
    await u.clear(input);
    await u.type(input, "1 200");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect(JSON.parse(String(calls(f, "PUT /services/s-new/prices/l1")[0][1]?.body))).toEqual({ price: "1200.00" });
    const own = await screen.findByRole("button", { name: /Замена масла, Москва-1: 1.200,00.₽ \(своя цена\)/ });
    expect(own).toHaveClass("font-bold");
    // Другая точка по-прежнему на базовой цене
    expect(screen.getByRole("button", { name: /Замена масла, Москва-2: 1.500,50.₽ \(базовая\)/ })).toBeInTheDocument();

    // Сброс к базовой
    await u.click(own);
    dlg = within(screen.getByRole("dialog", { name: "Цена: Замена масла" }));
    await u.click(dlg.getByRole("button", { name: "Сбросить к базовой" }));
    expect(await screen.findByRole("button", { name: /Замена масла, Москва-1: 1.500,50.₽ \(базовая\)/ })).toBeInTheDocument();
    expect(calls(f, "DELETE /services/s-new/prices/l1")).toHaveLength(1);
  });

  it("неверная цена не отправляется, ошибка у поля", async () => {
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /service-categories": () => json(200, [cat()]),
      "GET /services": () => page([svc()]),
      "GET /service-prices": () => json(200, []),
      "PUT /services/s1/prices/l1": () => json(200, {}),
    });
    open("/catalog");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Цены по точкам" }));
    await u.click(await screen.findByRole("button", { name: /Замена масла, Москва-1/ }));
    const dlg = within(screen.getByRole("dialog"));
    const input = dlg.getByLabelText("Цена на точке, ₽");
    await u.clear(input);
    await u.type(input, "12,345");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect(await dlg.findByRole("alert")).toHaveTextContent("Цена:");
    expect(calls(f, "PUT /services/s1/prices/l1")).toHaveLength(0);
  });
});

describe("409 unique_violation", () => {
  it("дубль кода услуги: сообщение из словаря у поля, текст сервера не виден", async () => {
    mockApi({
      ...base(makeUser("director")),
      "GET /service-categories": () => json(200, [cat()]),
      "GET /services": () => page([svc()]),
      "POST /services": () => apiError(409, "unique_violation"),
    });
    open("/catalog");
    const u = userEvent.setup();
    await waitFor(() => expect(screen.getByRole("button", { name: "+ Услуга" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "+ Услуга" }));
    const dlg = within(screen.getByRole("dialog", { name: "Новая услуга" }));
    await u.type(dlg.getByLabelText("Код"), "TO-1");
    await u.type(dlg.getByLabelText("Название"), "Дубль");
    await u.type(dlg.getByLabelText("Базовая цена, ₽"), "100");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect(await dlg.findByText(ERROR_MESSAGES.duplicate_service_code)).toBeInTheDocument();
    expect(dlg.getByLabelText(/^Код/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/SERVER TEXT|SQLSTATE/)).toBeNull();
  });

  it("дубль имени поста", async () => {
    mockApi({
      ...base(makeUser("director")),
      "GET /locations/l1/posts": () => json(200, [{ id: "po1", location_id: "l1", name: "Подъёмник 1", post_type: "lift", department: "service", sort_order: 0, is_active: true } satisfies Post]),
      "POST /locations/l1/posts": () => apiError(409, "unique_violation"),
    });
    open("/catalog");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Посты" }));
    expect((await screen.findAllByText("Подъёмник 1")).length).toBeGreaterThan(0);
    await u.click(screen.getByRole("button", { name: "+ Пост" }));
    const dlg = within(screen.getByRole("dialog", { name: "Новый пост" }));
    await u.type(dlg.getByLabelText("Название"), "Подъёмник 1");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect(await dlg.findByText(ERROR_MESSAGES.duplicate_post_name)).toBeInTheDocument();
  });

  it("дубль артикула запчасти", async () => {
    mockApi({
      ...base(makeUser("director")),
      "GET /parts": () => page([part()]),
      "POST /parts": () => apiError(409, "unique_violation"),
    });
    open("/catalog");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Запчасти и материалы" }));
    await u.click(await screen.findByRole("button", { name: "+ Позиция" }));
    const dlg = within(screen.getByRole("dialog", { name: "Новая позиция" }));
    await u.type(dlg.getByLabelText("Артикул"), "OIL-5W30");
    await u.type(dlg.getByLabelText("Название"), "Масло");
    await u.type(dlg.getByLabelText("Цена продажи, ₽"), "900");
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    expect(await dlg.findByText(ERROR_MESSAGES.duplicate_sku)).toBeInTheDocument();
  });
});

describe("активность и посты", () => {
  it("переключение активности услуги отправляет PATCH is_active без кода и категории", async () => {
    const f = mockApi({
      ...base(makeUser("director")),
      "GET /service-categories": () => json(200, [cat()]),
      "GET /services": () => page([svc()]),
      "PATCH /services/s1": () => json(200, svc({ is_active: false })),
    });
    open("/catalog");
    const u = userEvent.setup();
    await u.click((await screen.findAllByRole("button", { name: "Изменить услугу Замена масла" }))[0]);
    const dlg = within(screen.getByRole("dialog", { name: "Услуга" }));
    await u.click(dlg.getByLabelText("Активна"));
    await u.click(dlg.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(calls(f, "PATCH /services/s1")).toHaveLength(1));
    const body = JSON.parse(String(calls(f, "PATCH /services/s1")[0][1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({ is_active: false, base_price: "1500.00", norm_hours: "1.50" });
    expect(body).not.toHaveProperty("code");
    expect(body).not.toHaveProperty("category_id");
  });

  it("посты выбранной точки", async () => {
    const f = mockApi({
      ...base(makeUser("director"), [LOC1, LOC2]),
      "GET /locations/l1/posts": () => json(200, []),
      "GET /locations/l2/posts": () => json(200, [{ id: "po2", location_id: "l2", name: "Бокс 1", post_type: "detailing_box", department: "detailing", sort_order: 0, is_active: true } satisfies Post]),
    });
    open("/catalog");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Посты" }));
    expect(await screen.findByText("На этой точке постов пока нет")).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Точка", { selector: "#post-loc" }), "l2");
    expect((await screen.findAllByText("Бокс 1")).length).toBeGreaterThan(0);
    expect(calls(f, "GET /locations/l2/posts")).toHaveLength(1);
  });
});

describe("инъекции", () => {
  it("<script> в названиях выводится как текст", async () => {
    const evil = "<script>alert(1)</script>";
    mockApi({
      ...base(makeUser("director")),
      "GET /service-categories": () => json(200, [cat({ name: evil })]),
      "GET /services": () => page([svc({ name: evil, code: "X<b>1</b>" })]),
      "GET /parts": () => page([part({ name: evil, brand: "<img src=x onerror=alert(1)>" })]),
    });
    const { container } = open("/catalog");
    expect((await screen.findAllByText(evil)).length).toBeGreaterThan(0);
    expect(container.querySelector("script")).toBeNull();
    const u = userEvent.setup();
    await u.click(screen.getByRole("tab", { name: "Запчасти и материалы" }));
    expect((await screen.findAllByText("<img src=x onerror=alert(1)>")).length).toBeGreaterThan(0);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
