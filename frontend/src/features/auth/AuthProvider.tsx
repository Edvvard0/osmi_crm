import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, refreshSession, setAccessToken, setAuthLostHandler } from "@/shared/api/client";
import type { Session, User } from "@/shared/api/types";
import { readPref, writePref } from "@/shared/lib/storage";
import { clearCacheOnLogout, ensureCacheOwner } from "@/shared/pwa/cache";

type Status = "loading" | "authed" | "anon";

interface AuthCtx {
  user: User | null;
  status: Status;
  /** Сессия истекла: показываем сообщение на экране входа. */
  expired: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Выбранная точка: id или "all" (только руководитель). */
  locationId: string;
  setLocationId: (id: string) => void;
}

const Ctx = createContext<AuthCtx | null>(null);
const LOC_KEY = "crm.location";

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [expired, setExpired] = useState(false);
  const [locationId, setLoc] = useState<string>(() => readPref(LOC_KEY) ?? "all");

  // Bootstrap: access-токен живёт только в памяти, поэтому при загрузке получаем его по refresh-cookie.
  useEffect(() => {
    let alive = true;
    void refreshSession().then(async (s) => {
      // Кэш чтений другого пользователя удаляем до первого запроса экранов.
      if (s?.user) await ensureCacheOwner(s.user.id);
      if (!alive) return;
      setUser(s?.user ?? null);
      setStatus(s ? "authed" : "anon");
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    setAuthLostHandler(() => {
      setAccessToken(null);
      setUser(null);
      setStatus("anon");
      setExpired(true);
      qc.clear();
      void clearCacheOnLogout();
    });
    return () => setAuthLostHandler(null);
  }, [qc]);

  const login = useCallback(
    async (loginName: string, password: string) => {
      const s = await api<Session>("/auth/login", { body: { login: loginName, password } });
      // До первого запроса под новым пользователем: ключ кэша — полный URL, чужие ответы отдавать нельзя.
      await ensureCacheOwner(s.user.id);
      setAccessToken(s.access_token);
      qc.clear();
      setExpired(false);
      setUser(s.user);
      setStatus("authed");
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", skipAuthRetry: true, allowOffline: true });
    } catch {
      /* выходим локально в любом случае */
    }
    await clearCacheOnLogout();
    setAccessToken(null);
    qc.clear();
    setExpired(false);
    setUser(null);
    setStatus("anon");
  }, [qc]);

  const setLocationId = useCallback((id: string) => {
    setLoc(id);
    writePref(LOC_KEY, id);
  }, []);

  const value = useMemo(
    () => ({ user, status, expired, login, logout, locationId, setLocationId }),
    [user, status, expired, login, logout, locationId, setLocationId],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}

/** Текущий пользователь для экранов под защитой (RequireAuth гарантирует его наличие). */
export function useMe(): User {
  const { user } = useAuth();
  if (!user) throw new Error("not authenticated");
  return user;
}
