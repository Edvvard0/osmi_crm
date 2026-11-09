import { Navigate, Outlet, useLocation } from "react-router-dom";

import { ForbiddenPage } from "@/pages/ErrorPage";
import type { Role } from "@/shared/api/types";

import { useAuth } from "./AuthProvider";

export function Splash() {
  return (
    <div className="grid h-full place-items-center text-sm text-muted" role="status">
      Загрузка…
    </div>
  );
}

export function RequireAuth() {
  const { user, status } = useAuth();
  const loc = useLocation();
  if (status === "loading") return <Splash />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <Outlet />;
}

export function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return <ForbiddenPage />;
  return <Outlet />;
}
