import clsx from "clsx";
import { NavLink, Outlet } from "react-router-dom";

import { useMe, useAuth } from "@/features/auth/AuthProvider";
import { useActiveLocation } from "@/features/locations/api";
import { GlobalSearch } from "@/features/search/CommandPalette";
import type { Role } from "@/shared/api/types";
import { Button } from "@/shared/ui/ui";

import { ErrorBoundary } from "./ErrorBoundary";
import { OfflineBanner } from "./OfflineBanner";

interface NavItem { to: string; label: string; roles: Role[] }

const NAV: NavItem[] = [
  { to: "/", label: "Рабочий стол", roles: ["mechanic", "manager", "director"] },
  { to: "/clients", label: "Клиенты", roles: ["manager", "director"] },
  { to: "/users", label: "Сотрудники", roles: ["director"] },
  { to: "/locations", label: "Точки", roles: ["director"] },
  { to: "/settings", label: "Настройки", roles: ["mechanic", "manager", "director"] },
];

const linkCls = ({ isActive }: { isActive: boolean }) =>
  clsx("rounded px-3 py-2 text-sm", isActive ? "bg-accent text-accent-fg" : "text-muted hover:bg-border/50");

function LocationSwitcher() {
  const { items, value, set, isDirector } = useActiveLocation();
  if (!isDirector && items.length <= 1) {
    return <span className="truncate text-sm text-muted">{items[0]?.name ?? ""}</span>;
  }
  return (
    <select
      aria-label="Точка"
      value={value}
      onChange={(e) => set(e.target.value)}
      className="min-h-9 max-w-[50vw] rounded border border-border bg-surface px-2 text-sm text-fg"
    >
      {isDirector && <option value="all">Все точки</option>}
      {items.map((l) => (
        <option key={l.id} value={l.id}>{l.name}</option>
      ))}
    </select>
  );
}

export function Layout() {
  const me = useMe();
  const { logout } = useAuth();
  const nav = NAV.filter((n) => n.roles.includes(me.role));
  return (
    <div className="flex h-full flex-col md:flex-row">
      {/* Desktop: сайдбар */}
      <aside className="hidden w-56 shrink-0 border-r border-border bg-surface p-3 md:block" aria-label="Навигация">
        <div className="mb-4 px-3 text-sm font-semibold">CRM</div>
        <nav className="flex flex-col gap-1">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={linkCls}>{n.label}</NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-2 border-b border-border bg-surface px-4 py-2">
          <LocationSwitcher />
          <div className="flex items-center gap-2">
            {(me.role === "manager" || me.role === "director") && <GlobalSearch />}
            <span className="hidden truncate text-sm text-muted sm:inline">{me.full_name}</span>
            <Button variant="ghost" onClick={() => void logout()}>Выйти</Button>
          </div>
        </header>
        <OfflineBanner />
        <main className="flex-1 overflow-y-auto p-4 pb-20 md:p-6 md:pb-6">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      {/* Mobile: нижняя панель */}
      <nav className="fixed inset-x-0 bottom-0 flex justify-around border-t border-border bg-surface p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] md:hidden" aria-label="Навигация">
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} className={linkCls}>{n.label}</NavLink>
        ))}
      </nav>
    </div>
  );
}
