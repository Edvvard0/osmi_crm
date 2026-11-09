import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import type { ReactNode } from "react";

import type { Role } from "@/shared/api/types";
import { NotFoundPage } from "@/pages/ErrorPage";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { RequireAuth, RequireRole } from "@/features/auth/guards";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { onRecover } from "@/shared/lib/connectivity";
import { ToastProvider } from "@/shared/ui/toast";
import { Loading } from "@/shared/ui/ui";

import { ErrorBoundary } from "./ErrorBoundary";
import { Layout } from "./Layout";
import { installGlobalHandlers } from "./globalHandlers";
import { createQueryClient } from "./queryClient";

// Экраны грузятся по требованию (React.lazy): начальный бандл — только оболочка, вход и рабочий стол.
// Suspense даёт Layout вокруг Outlet.
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const CatalogPage = lazy(() => import("@/pages/catalog/CatalogPage").then((m) => ({ default: m.CatalogPage })));
const ClientFormPage = lazy(() => import("@/pages/clients/ClientFormPage").then((m) => ({ default: m.ClientFormPage })));
const ClientPage = lazy(() => import("@/pages/clients/ClientPage").then((m) => ({ default: m.ClientPage })));
const ClientsPage = lazy(() => import("@/pages/clients/ClientsPage").then((m) => ({ default: m.ClientsPage })));
const VehiclePage = lazy(() => import("@/pages/clients/VehiclePage").then((m) => ({ default: m.VehiclePage })));
const LocationPage = lazy(() => import("@/pages/locations/LocationPage").then((m) => ({ default: m.LocationPage })));
const LocationsPage = lazy(() => import("@/pages/locations/LocationsPage").then((m) => ({ default: m.LocationsPage })));
const UserPage = lazy(() => import("@/pages/users/UserPage").then((m) => ({ default: m.UserPage })));
const UsersPage = lazy(() => import("@/pages/users/UsersPage").then((m) => ({ default: m.UsersPage })));
const VehicleEditPage = lazy(() => import("@/pages/clients/VehicleFormPage").then((m) => ({ default: m.VehicleEditPage })));
const VehicleNewPage = lazy(() => import("@/pages/clients/VehicleFormPage").then((m) => ({ default: m.VehicleNewPage })));

// Календарь тяжёлый (сетка, перетаскивание) — грузится отдельным чанком только при заходе на /calendar.
const CalendarPage = lazy(() => import("@/pages/calendar/CalendarPage").then((m) => ({ default: m.CalendarPage })));

// Маршруты модулей: features/<имя>/routes.tsx экспортирует `routes: FeatureRoute[]`.
export interface FeatureRoute { path: string; roles: Role[]; element: ReactNode }
const featureRoutes = Object.values(
  import.meta.glob<{ routes: FeatureRoute[] }>("../features/*/routes.tsx", { eager: true }),
).flatMap((m) => m.routes);
const routeGroupMap = new Map<string, FeatureRoute[]>();
for (const r of featureRoutes) {
  const key = [...r.roles].sort().join(",");
  routeGroupMap.set(key, [...(routeGroupMap.get(key) ?? []), r]);
}
const routeGroups = [...routeGroupMap];

export function App() {
  const [qc] = useState(createQueryClient);
  useEffect(() => installGlobalHandlers(), []);
  // Связь восстановилась — перезапрашиваем активные данные (вместо показанных из офлайн-кэша).
  useEffect(() => onRecover(() => void qc.invalidateQueries()), [qc]);
  return (
    <ErrorBoundary>
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <AuthProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route element={<RequireAuth />}>
                  <Route element={<Layout />}>
                    <Route index element={<DashboardPage />} />
                    <Route path="settings" element={<SettingsPage />} />
                    <Route element={<RequireRole roles={["manager", "director"]} />}>
                      <Route path="clients" element={<ClientsPage />} />
                      <Route path="clients/new" element={<ClientFormPage />} />
                      <Route path="clients/:id" element={<ClientPage />} />
                      <Route path="clients/:id/edit" element={<ClientFormPage />} />
                      <Route path="clients/:id/vehicles/new" element={<VehicleNewPage />} />
                      <Route path="vehicles/:id" element={<VehiclePage />} />
                      <Route path="vehicles/:id/edit" element={<VehicleEditPage />} />
                    </Route>
                    <Route element={<RequireRole roles={["manager", "director"]} />}>
                      <Route path="catalog" element={<CatalogPage />} />
                      <Route
                        path="calendar"
                        element={
                          <Suspense fallback={<Loading />}>
                            <CalendarPage />
                          </Suspense>
                        }
                      />
                    </Route>
                    <Route element={<RequireRole roles={["director"]} />}>
                      <Route path="users" element={<UsersPage />} />
                      <Route path="users/:id" element={<UserPage />} />
                      <Route path="locations" element={<LocationsPage />} />
                      <Route path="locations/:id" element={<LocationPage />} />
                    </Route>
                    {routeGroups.map(([key, group]) => (
                      <Route key={key} element={<RequireRole roles={group[0].roles} />}>
                        {group.map((r) => (
                          <Route key={r.path} path={r.path} element={r.element} />
                        ))}
                      </Route>
                    ))}
                    <Route path="*" element={<NotFoundPage />} />
                  </Route>
                </Route>
              </Routes>
            </BrowserRouter>
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
