import { QueryClientProvider, useMutation } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { ErrorBoundary } from "@/app/ErrorBoundary";
import { OfflineBanner, formatHm } from "@/app/OfflineBanner";
import { MUTATION_NETWORK_ERROR_TEXT, createQueryClient } from "@/app/queryClient";
import { UpdatePrompt } from "@/app/UpdatePrompt";
import { SystemCard } from "@/features/system/SystemCard";
import type { SystemStatus } from "@/features/system/types";
import { api } from "@/shared/api/client";
import type { AppError } from "@/shared/api/errors";
import {
  API_CACHE_NAME,
  apiCacheUrlPattern,
  isApiCacheablePath,
  isApiCacheableRequest,
} from "@/shared/lib/apiCachePolicy";
import { resetReporterForTests, safePath, scrub } from "@/shared/lib/reporter";
import { clearCacheOnLogout, ensureCacheOwner } from "@/shared/pwa/cache";
import { resetDirtyFormsForTests } from "@/shared/pwa/dirtyForms";
import { resetUpdateStateForTests, setApplyForTests, setNeedRefresh } from "@/shared/pwa/updater";
import { ToastProvider } from "@/shared/ui/toast";
import { Button, OFFLINE_HINT } from "@/shared/ui/ui";

import { type Handler, LOC1, LOC2, apiError, calls, json, makeUser, mockApi, session } from "./mockApi";

const goOffline = () => act(() => void window.dispatchEvent(new Event("offline")));
const goOnline = () => act(() => void window.dispatchEvent(new Event("online")));

beforeEach(() => {
  resetReporterForTests();
  resetUpdateStateForTests();
  resetDirtyFormsForTests();
});
afterEach(() => vi.unstubAllGlobals());

function jsonWith(status: number, body: unknown, headers: Record<string, string>) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

describe("C-04: баннер «Нет соединения»", () => {
  const renderBanner = () =>
    render(
      <MemoryRouter>
        <OfflineBanner />
      </MemoryRouter>,
    );

  it("по событию offline: role=alert «Нет соединения»; по online исчезает", async () => {
    renderBanner();
    expect(screen.queryByRole("alert")).toBeNull();
    goOffline();
    expect(screen.getByRole("alert")).toHaveTextContent(/^Нет соединения$/);
    goOnline();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("сетевая ошибка запроса показывает баннер, успешный ответ — убирает", async () => {
    const f = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"));
    f.mockResolvedValue(json(200, []));
    vi.stubGlobal("fetch", f);
    renderBanner();
    await act(async () => {
      await api("/work-orders").catch(() => undefined);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Нет соединения");
    await act(async () => {
      await api("/work-orders");
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ответ из офлайн-кэша: «Показаны данные на HH:MM» по заголовку Date исходного ответа", async () => {
    const date = new Date("2026-03-04T09:07:00Z");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonWith(200, [], { "X-From-Cache": "1", Date: date.toUTCString() })));
    renderBanner();
    await act(async () => {
      await api("/work-orders");
    });
    expect(screen.getByRole("alert")).toHaveTextContent(`Нет соединения. Показаны данные на ${formatHm(date.getTime())}`);
  });

  it("502/503/504 — это не офлайн: баннер не показывается", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(apiError(503, "service_unavailable")));
    renderBanner();
    await act(async () => {
      await api("/work-orders").catch(() => undefined);
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("виден на экране входа", async () => {
    mockApi({ "POST /auth/refresh": () => apiError(401, "invalid_token") });
    window.history.pushState({}, "", "/login");
    render(<App />);
    await screen.findByRole("button", { name: "Войти" });
    goOffline();
    expect(screen.getByRole("alert")).toHaveTextContent(/^Нет соединения/);
  });
});

describe("офлайн: блокировка изменяющих действий", () => {
  it("POST/PATCH/DELETE не уходят в сеть и отклоняются с подсказкой; GET уходит", async () => {
    const f = mockApi({ "GET /work-orders": () => json(200, []) });
    goOffline();
    for (const method of ["POST", "PATCH", "DELETE"] as const) {
      const err = await api<never>("/clients", { method, body: { name: "x" } }).catch((e: unknown) => e as AppError);
      expect(err.code).toBe("offline");
      expect(err.message).toBe(OFFLINE_HINT);
    }
    expect(f).not.toHaveBeenCalled();
    await expect(api("/work-orders")).resolves.toEqual([]);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("allowOffline (выход из системы) разрешён", async () => {
    const f = mockApi({ "POST /auth/logout": () => json(204) });
    goOffline();
    await api("/auth/logout", { method: "POST", allowOffline: true });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("кнопка отправки формы и «опасная» кнопка блокируются с подсказкой, безопасные остаются доступными", () => {
    render(
      <div>
        <Button type="submit">Сохранить</Button>
        <Button variant="danger">Удалить</Button>
        <Button variant="secondary" offlineSafe>Повторить</Button>
      </div>,
    );
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled();
    goOffline();
    for (const name of ["Сохранить", "Удалить"]) {
      const b = screen.getByRole("button", { name });
      expect(b).toBeDisabled();
      expect(b).toHaveAttribute("title", OFFLINE_HINT);
    }
    expect(screen.getByRole("button", { name: "Повторить" })).toBeEnabled();
    goOnline();
  });

  it("отклонённая мутация показывает toast с подсказкой", async () => {
    mockApi({});
    function Probe() {
      const m = useMutation({ mutationFn: () => api("/clients", { method: "POST", body: { a: 1 } }) });
      return <button onClick={() => m.mutate()}>go</button>;
    }
    render(
      <QueryClientProvider client={createQueryClient()}>
        <ToastProvider>
          <Probe />
        </ToastProvider>
      </QueryClientProvider>,
    );
    goOffline();
    await userEvent.setup().click(screen.getByText("go"));
    expect(await screen.findByRole("alert")).toHaveTextContent(OFFLINE_HINT);
  });

  it("сетевая ошибка при изменении: toast «Нет соединения. Действие не выполнено»", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    function Probe() {
      const m = useMutation({ mutationFn: () => api("/clients", { method: "POST", body: { a: 1 } }) });
      return <button onClick={() => m.mutate()}>go</button>;
    }
    render(
      <QueryClientProvider client={createQueryClient()}>
        <ToastProvider>
          <Probe />
        </ToastProvider>
      </QueryClientProvider>,
    );
    await userEvent.setup().click(screen.getByText("go"));
    expect(await screen.findByText(MUTATION_NETWORK_ERROR_TEXT)).toBeInTheDocument();
    expect(MUTATION_NETWORK_ERROR_TEXT).toBe("Нет соединения. Действие не выполнено");
  });
});

describe("C-06: ErrorBoundary", () => {
  const SECRET = "Иван Петров ivan@example.com +7 (900) 123-45-67 token=eyJhbGciOi.eyJzdWIi.sig";

  function bombFetch() {
    const f = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", f);
    return f;
  }

  it("экран ошибки без деталей, кнопки «Обновить страницу» и «На главную»", () => {
    bombFetch();
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Bomb = (): never => {
      throw new Error(SECRET);
    };
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    expect(screen.getByRole("heading", { name: "Что-то пошло не так" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обновить страницу" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "На главную" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("ivan@example.com");
    expect(document.body.textContent).not.toContain("Петров");
    spy.mockRestore();
  });

  it("в client-errors уходит только обезличенный текст и путь без query и идентификаторов", () => {
    const f = bombFetch();
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    window.history.pushState({}, "", "/clients/12345?q=Иванов");
    const Bomb = (): never => {
      throw new Error(SECRET);
    };
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/client-errors");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body)) as Record<string, string>;
    const raw = JSON.stringify(body);
    for (const leak of ["ivan@example.com", "Иванов", "123-45-67", "eyJhbGciOi", "12345"]) expect(raw).not.toContain(leak);
    expect(body.url).toBe("/clients/:id");
    expect(body.message).toContain("[email]");
    expect(Object.keys(body).sort()).toEqual(["kind", "message", "stack", "url"]);
    expect(body.message.length).toBeLessThanOrEqual(500);
    expect(body.kind.length).toBeLessThanOrEqual(32);
    spy.mockRestore();
    window.history.pushState({}, "", "/");
  });

  it("при смене resetKey (переход на другой экран) ошибка сбрасывается", () => {
    bombFetch();
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Bomb = ({ boom }: { boom: boolean }) => {
      if (boom) throw new Error("x");
      return <p>экран работает</p>;
    };
    const { rerender } = render(<ErrorBoundary resetKey="/a"><Bomb boom /></ErrorBoundary>);
    expect(screen.getByText("Что-то пошло не так")).toBeInTheDocument();
    rerender(<ErrorBoundary resetKey="/b"><Bomb boom={false} /></ErrorBoundary>);
    expect(screen.getByText("экран работает")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("scrub/safePath убирают персональные данные", () => {
    expect(scrub("a@b.ru и +7 900 123-45-67")).toBe("[email] и [number]");
    expect(scrub("GET /x?phone=79001234567#frag")).toBe("GET /x?");
    expect(safePath("/orders/0b6f1c2e-1111-4222-8333-444455556666/print?x=1")).toBe("/orders/:id/print");
  });
});

describe("C-05: плашка «Доступна новая версия»", () => {
  it("не показывается, пока нет обновления; «Позже» скрывает; «Обновить» применяет", async () => {
    const apply = vi.fn().mockResolvedValue(undefined);
    setApplyForTests(apply);
    render(<UpdatePrompt />);
    expect(screen.queryByText("Доступна новая версия")).toBeNull();
    act(() => setNeedRefresh());
    expect(screen.getByText("Доступна новая версия")).toBeInTheDocument();

    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Позже" }));
    expect(screen.queryByText("Доступна новая версия")).toBeNull();
    expect(apply).not.toHaveBeenCalled();

    act(() => setNeedRefresh());
    await u.click(screen.getByRole("button", { name: "Обновить" }));
    expect(apply).toHaveBeenCalledWith(true);
  });

  it("при несохранённой форме сначала спрашивает подтверждение", async () => {
    const apply = vi.fn().mockResolvedValue(undefined);
    setApplyForTests(apply);
    render(
      <div>
        <UpdatePrompt />
        <form>
          <input aria-label="Комментарий" />
        </form>
      </div>,
    );
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Комментарий"), "текст");
    act(() => setNeedRefresh());
    await u.click(screen.getByRole("button", { name: "Обновить" }));
    expect(screen.getByText(/Несохранённые данные в форме будут потеряны/)).toBeInTheDocument();
    expect(apply).not.toHaveBeenCalled();

    await u.click(screen.getByRole("button", { name: "Отмена" }));
    expect(apply).not.toHaveBeenCalled();
    await u.click(screen.getByRole("button", { name: "Обновить" }));
    await u.click(screen.getByRole("button", { name: "Всё равно обновить" }));
    expect(apply).toHaveBeenCalledWith(true);
  });

  it("чистая форма (после отправки) не мешает обновлению", async () => {
    const apply = vi.fn().mockResolvedValue(undefined);
    setApplyForTests(apply);
    render(
      <div>
        <UpdatePrompt />
        <form onSubmit={(e) => e.preventDefault()}>
          <input aria-label="Поле" />
          <button type="submit">Отправить</button>
        </form>
      </div>,
    );
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Поле"), "a");
    await u.click(screen.getByRole("button", { name: "Отправить" }));
    act(() => setNeedRefresh());
    await u.click(screen.getByRole("button", { name: "Обновить" }));
    expect(apply).toHaveBeenCalledWith(true);
  });
});

describe("очистка кэша api-read-v1", () => {
  let del: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    del = vi.fn().mockResolvedValue(true);
    vi.stubGlobal("caches", { delete: del });
  });

  const director = makeUser("director");
  const handlers = (over: Record<string, Handler> = {}): Record<string, Handler> => ({
    "POST /auth/refresh": () => json(200, session(director)),
    "GET /locations": () => json(200, [LOC1, LOC2]),
    "POST /auth/logout": () => json(204),
    "GET /system/status": () => apiError(404, "not_found"),
    ...over,
  });
  const open = (path = "/") => {
    window.history.pushState({}, "", path);
    return render(<App />);
  };

  it("clearCacheOnLogout удаляет именно api-read-v1", async () => {
    await clearCacheOnLogout();
    expect(del).toHaveBeenCalledWith(API_CACHE_NAME);
    expect(API_CACHE_NAME).toBe("api-read-v1");
  });

  it("ensureCacheOwner чистит кэш только при смене пользователя", async () => {
    await ensureCacheOwner("u1");
    del.mockClear();
    await ensureCacheOwner("u1");
    expect(del).not.toHaveBeenCalled();
    await ensureCacheOwner("u2");
    expect(del).toHaveBeenCalledTimes(1);
  });

  it("без Cache API ничего не падает", async () => {
    vi.stubGlobal("caches", undefined);
    await expect(clearCacheOnLogout()).resolves.toBeUndefined();
  });

  it("выход из системы", async () => {
    mockApi(handlers());
    open();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Выйти" }));
    await screen.findByRole("button", { name: "Войти" });
    expect(del).toHaveBeenCalledWith("api-read-v1");
  });

  it("выход офлайн: локальный выход и очистка кэша выполняются", async () => {
    mockApi(handlers());
    open();
    const btn = await screen.findByRole("button", { name: "Выйти" });
    goOffline();
    await userEvent.setup().click(btn);
    await screen.findByRole("button", { name: "Войти" });
    expect(del).toHaveBeenCalledWith("api-read-v1");
  });

  it("принудительный выход (сессия истекла)", async () => {
    let refreshes = 0;
    mockApi(
      handlers({
        "POST /auth/refresh": () => (++refreshes === 1 ? json(200, session(director)) : apiError(401, "invalid_token")),
        "GET /system/status": () => apiError(401, "invalid_token"),
      }),
    );
    open();
    expect(await screen.findByText("Сессия истекла, войдите снова")).toBeInTheDocument();
    expect(del).toHaveBeenCalledWith("api-read-v1");
  });

  it("вход другого пользователя: кэш очищается до первого запроса данных", async () => {
    localStorage.setItem("crm.cache-owner", "u-manager");
    const order: string[] = [];
    del.mockImplementation(async () => {
      order.push("cache-delete");
      return true;
    });
    mockApi(
      handlers({
        "POST /auth/refresh": () => apiError(401, "invalid_token"),
        "POST /auth/login": () => json(200, session(director)),
        "GET /locations": () => {
          order.push("data-request");
          return json(200, [LOC1, LOC2]);
        },
      }),
    );
    open("/login");
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Логин"), "director");
    await u.type(screen.getByLabelText("Пароль"), "demo-password-123");
    await u.click(screen.getByRole("button", { name: "Войти" }));
    await screen.findByText("Рабочий стол руководителя");
    expect(order.indexOf("cache-delete")).toBeGreaterThanOrEqual(0);
    expect(order.indexOf("cache-delete")).toBeLessThan(order.indexOf("data-request"));
    expect(localStorage.getItem("crm.cache-owner")).toBe("u-director");
  });

  it("тот же пользователь после перезапуска: кэш сохраняется", async () => {
    localStorage.setItem("crm.cache-owner", "u-director");
    mockApi(handlers());
    open();
    await screen.findByText("Рабочий стол руководителя");
    expect(del).not.toHaveBeenCalled();
  });
});

describe("политика офлайн-кэша ответов API", () => {
  it.each([
    "/api/v1/work-orders",
    "/api/v1/work-orders?status=in_progress&limit=50",
    "/api/v1/work-orders/0b6f1c2e-1111-4222-8333-444455556666",
    "/api/v1/appointments?date_from=2026-03-01",
    "/api/v1/services",
    "/api/v1/service-categories",
    "/api/v1/posts",
    "/api/v1/locations",
    "/api/v1/parts?q=filter",
    "/api/v1/mechanic/tasks",
  ])("кэшируется: %s", (p) => {
    expect(isApiCacheablePath(p)).toBe(true);
    expect(apiCacheUrlPattern().test(`https://crm.example.com${p}`)).toBe(true);
  });

  it.each([
    "/api/v1/auth/refresh",
    "/api/v1/me",
    "/api/v1/users",
    "/api/v1/clients",
    "/api/v1/vehicles/1",
    "/api/v1/search?q=a",
    "/api/v1/payments",
    "/api/v1/expenses",
    "/api/v1/cash/report",
    "/api/v1/stock/movements",
    "/api/v1/payroll",
    "/api/v1/reports/revenue",
    "/api/v1/audit-log",
    "/api/v1/settings",
    "/api/v1/telegram/status",
    "/api/v1/health",
    "/api/v1/system/status",
    "/api/v1/work-orders/0b6f/payments",
    "/api/v1/work-orders/0b6f/print",
    "/api/v1/unknown",
    "/other/work-orders",
  ])("не кэшируется: %s", (p) => {
    expect(isApiCacheablePath(p)).toBe(false);
    expect(apiCacheUrlPattern().test(`https://crm.example.com${p}`)).toBe(false);
  });

  it("только GET", () => {
    expect(isApiCacheableRequest("GET", "/api/v1/work-orders")).toBe(true);
    for (const m of ["POST", "PATCH", "PUT", "DELETE"]) expect(isApiCacheableRequest(m, "/api/v1/work-orders")).toBe(false);
  });

  it("правило service worker: 4 с, 100 записей, 24 ч, NetworkFirst", async () => {
    const mod = await import("@/shared/lib/apiCachePolicy");
    expect(mod.API_CACHE_TIMEOUT_SECONDS).toBe(4);
    expect(mod.API_CACHE_MAX_ENTRIES).toBe(100);
    expect(mod.API_CACHE_MAX_AGE_SECONDS).toBe(86_400);
  });
});

describe("D-01: карточка «Система»", () => {
  const STATUS: SystemStatus = {
    server_time: "2026-03-04T10:00:00Z",
    app_timezone: "Europe/Moscow",
    env: "prod",
    migrations: { current: "0012", head: "0012" },
    worker: { last_heartbeat_at: "2026-03-04T09:59:30Z", ok: true },
    outbox: { pending: 2, failed_24h: 0, oldest_pending_age_seconds: 20 },
    telegram: { mode: "polling", bot_username: "crm_bot" },
    last_backup_at: "2026-03-04T03:00:00Z",
    version: "1.0.0",
  };

  const withClient = (ui: React.ReactNode) => render(<QueryClientProvider client={createQueryClient()}>{ui}</QueryClientProvider>);

  it("скелетон при загрузке", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    withClient(<SystemCard />);
    expect(screen.getByRole("heading", { name: "Система" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Загрузка состояния системы" })).toBeInTheDocument();
  });

  it("показывает воркер, очередь уведомлений и резервную копию", async () => {
    mockApi({ "GET /system/status": () => json(200, STATUS) });
    withClient(<SystemCard />);
    expect(await screen.findByText("Воркер")).toBeInTheDocument();
    expect(screen.getByText("Очередь уведомлений")).toBeInTheDocument();
    expect(screen.getByText("Резервная копия")).toBeInTheDocument();
    expect(screen.getByText(/в очереди 2, ошибок за сутки 0/)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Загрузка состояния системы" })).toBeNull();
  });

  it("воркер не отвечает и есть ошибки отправки — это видно", async () => {
    mockApi({
      "GET /system/status": () =>
        json(200, { ...STATUS, worker: { last_heartbeat_at: null, ok: false }, outbox: { pending: 5, failed_24h: 3, oldest_pending_age_seconds: 4000 }, last_backup_at: null }),
    });
    withClient(<SystemCard />);
    expect(await screen.findByText(/не отвечает/)).toBeInTheDocument();
    expect(screen.getAllByText("Ошибка")).toHaveLength(2);
    expect(screen.getAllByText("нет данных").length).toBeGreaterThan(0);
  });

  it("ошибка: «Нет данных о состоянии системы», без toast", async () => {
    mockApi({ "GET /system/status": () => apiError(500, "internal_error") });
    render(
      <QueryClientProvider client={createQueryClient()}>
        <ToastProvider>
          <SystemCard />
        </ToastProvider>
      </QueryClientProvider>,
    );
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("Нет данных о состоянии системы");
  });

  it("на рабочем столе руководителя карточка есть, у менеджера — нет", async () => {
    const asRole = (role: "director" | "manager") =>
      mockApi({
        "POST /auth/refresh": () => json(200, session(makeUser(role))),
        "GET /locations": () => json(200, [LOC1]),
        "GET /system/status": () => json(200, STATUS),
      });
    window.history.pushState({}, "", "/");
    asRole("director");
    const r = render(<App />);
    expect(await screen.findByRole("heading", { name: "Система" })).toBeInTheDocument();
    r.unmount();

    const f = asRole("manager");
    render(<App />);
    await screen.findByText("Рабочий стол менеджера");
    expect(screen.queryByRole("heading", { name: "Система" })).toBeNull();
    expect(calls(f, "GET /system/status")).toHaveLength(0);
  });
});
