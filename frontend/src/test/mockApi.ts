import { vi } from "vitest";

import type { CrmLocation, Role, Session, User } from "@/shared/api/types";

export interface Req {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
  auth: string | null;
}
export type Handler = (r: Req) => Response;

export function json(status: number, body?: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
export const apiError = (status: number, code: string, fields: Record<string, string> = {}, headers: Record<string, string> = {}) =>
  json(status, { error: { code, message: "SERVER TEXT SQLSTATE", fields, request_id: "r-1" } }, headers);

/** Подмена fetch по контракту: ключ маршрута — "METHOD /path" (без /api/v1 и query). */
export function mockApi(routes: Record<string, Handler>) {
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const h = routes[`${method} ${path}`];
    if (!h) return apiError(404, "not_found");
    const headers = new Headers(init?.headers);
    return h({
      method,
      path,
      query: url.searchParams,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      auth: headers.get("Authorization"),
    });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

export const calls = (f: ReturnType<typeof mockApi>, key: string) =>
  f.mock.calls.filter(([i, init]) => `${(init?.method ?? "GET").toUpperCase()} ${String(i).replace(/^\/api\/v1/, "").split("?")[0]}` === key);

export const LOC1: CrmLocation = { id: "l1", name: "Москва-1", address: "ул. Тестовая, 1", phone: null, is_active: true };
export const LOC2: CrmLocation = { id: "l2", name: "Москва-2", address: "ул. Другая, 2", phone: "+7 900 000-00-00", is_active: true };

export function makeUser(role: Role, over: Partial<User> = {}): User {
  return {
    id: `u-${role}`,
    login: role,
    full_name: `Иван ${role}`,
    role,
    is_active: true,
    location_ids: ["l1"],
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

export const session = (user: User, token = "tok1"): Session => ({ access_token: token, expires_in: 900, user });
