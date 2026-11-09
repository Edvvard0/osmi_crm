import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { ErrorBoundary } from "@/app/ErrorBoundary";
import { installGlobalHandlers } from "@/app/globalHandlers";
import { api } from "@/shared/api/client";
import { AppError, ERROR_MESSAGES } from "@/shared/api/errors";
import { resetReporterForTests } from "@/shared/lib/reporter";
import { ToastProvider } from "@/shared/ui/toast";

import { LOC1, json, makeUser, mockApi, session } from "./mockApi";

const SECRET = "SQLSTATE[23505] relation users Traceback secret";

function mockFetch(status: number, body?: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", f);
  return f;
}

beforeEach(() => resetReporterForTests());
afterEach(() => vi.unstubAllGlobals());

describe("API client: сообщение для каждого HTTP-кода", () => {
  const cases: [number, string][] = [
    [400, "bad_request"], [401, "unauthorized"], [403, "forbidden"], [404, "not_found"],
    [409, "conflict"], [413, "payload_too_large"], [422, "validation_error"],
    [429, "rate_limited"], [500, "internal_error"], [502, "service_unavailable"], [503, "service_unavailable"], [504, "service_unavailable"],
  ];
  it.each(cases)("%i → %s", async (status, code) => {
    mockFetch(status, { error: { message: SECRET } });
    const err = await api<never>("/x", { skipAuthRetry: true }).catch((e: unknown) => e as AppError);
    expect(err).toBeInstanceOf(AppError);
    expect(err.code).toBe(code);
    expect(err.message).toBe(ERROR_MESSAGES[code]);
    expect(err.message).not.toContain("SQLSTATE");
  });

  it("берёт код и поля из ответа сервера, но не его message", async () => {
    mockFetch(409, { error: { code: "unique_violation", message: SECRET, fields: { phone: "x" }, request_id: "r1" } });
    const err = await api<never>("/x").catch((e: unknown) => e as AppError);
    expect(err.code).toBe("unique_violation");
    expect(err.fields).toEqual({ phone: "x" });
    expect(err.requestId).toBe("r1");
    expect(err.message).not.toContain(SECRET);
  });

  it("неизвестный код от сервера → безопасное сообщение", async () => {
    mockFetch(418, { error: { code: "weird_code" } });
    const err = await api<never>("/x").catch((e: unknown) => e as AppError);
    expect(err.message).toBe(ERROR_MESSAGES.unknown);
  });

  it("сеть недоступна → network_error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch http://10.0.0.5:5432")));
    const err = await api<never>("/x").catch((e: unknown) => e as AppError);
    expect(err.code).toBe("network_error");
    expect(err.message).not.toContain("10.0.0.5");
  });

  it("не-JSON ответ с 500 не ломает клиент", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>stack</html>", { status: 500 })));
    const err = await api<never>("/x").catch((e: unknown) => e as AppError);
    expect(err.code).toBe("internal_error");
  });

  it("401 → один refresh и повтор запроса", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "t" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    await expect(api("/me")).resolves.toEqual({ ok: 1 });
    expect(f).toHaveBeenCalledTimes(3);
  });
});

describe("Error Boundary", () => {
  it("вместо белого экрана показывает C-06 и не выводит текст ошибки", () => {
    mockFetch(204);
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Bomb = () => {
      throw new Error(SECRET);
    };
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    expect(screen.getByText("Что-то пошло не так")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SQLSTATE");
    spy.mockRestore();
  });
});

describe("глобальные обработчики", () => {
  it("unhandledrejection → toast с безопасным текстом и отправка на сервер", async () => {
    const f = mockFetch(204);
    const off = installGlobalHandlers();
    render(<ToastProvider><div /></ToastProvider>);
    const ev = new Event("unhandledrejection") as PromiseRejectionEvent;
    Object.assign(ev, { reason: new Error(SECRET), preventDefault: () => undefined });
    act(() => {
      window.dispatchEvent(ev);
    });
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toBe(ERROR_MESSAGES.unknown);
    expect(document.body.textContent).not.toContain("SQLSTATE");
    expect(f).toHaveBeenCalledWith("/api/v1/client-errors", expect.anything());
    off();
  });
});

describe("маршруты и офлайн", () => {
  const authed = () =>
    mockApi({
      "POST /auth/refresh": () => json(200, session(makeUser("manager"))),
      "GET /locations": () => json(200, [LOC1]),
    });

  it("несуществующий адрес → «Не найдено»", async () => {
    authed();
    window.history.pushState({}, "", "/no/such/page");
    render(<App />);
    expect(await screen.findByText("Не найдено")).toBeInTheDocument();
  });

  it("баннер «Нет соединения» при offline", async () => {
    authed();
    window.history.pushState({}, "", "/");
    render(<App />);
    await screen.findByText("Рабочий стол менеджера");
    await screen.findByText("Москва-1"); // шапка полностью загружена, слушатели online/offline подписаны
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    // Блоки главной без моков тоже показывают role=alert — проверяем именно баннер.
    expect(screen.getByText(/^Нет соединения/)).toHaveAttribute("role", "alert");
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(screen.queryByText(/^Нет соединения/)).toBeNull());
  });
});
