import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ErrorPage, NotFoundPage } from "@/pages/ErrorPage";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { RequireAuth, RequireRole } from "@/features/auth/guards";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { CatalogPage } from "@/pages/catalog/CatalogPage";
import { ClientFormPage } from "@/pages/clients/ClientFormPage";
import { ClientPage } from "@/pages/clients/ClientPage";
import { ClientsPage } from "@/pages/clients/ClientsPage";
import { VehicleEditPage, VehicleNewPage } from "@/pages/clients/VehicleFormPage";
import { VehiclePage } from "@/pages/clients/VehiclePage";
import { LocationPage } from "@/pages/locations/LocationPage";
import { LocationsPage } from "@/pages/locations/LocationsPage";
import { UserPage } from "@/pages/users/UserPage";
import { UsersPage } from "@/pages/users/UsersPage";
import { ToastProvider } from "@/shared/ui/toast";
import { Loading } from "@/shared/ui/ui";

import { ErrorBoundary } from "./ErrorBoundary";
import { Layout } from "./Layout";
import { installGlobalHandlers } from "./globalHandlers";
import { createQueryClient } from "./queryClient";

// Календарь тяжёлый (сетка, перетаскивание) — грузится отдельным чанком только при заходе на /calendar.
const CalendarPage = lazy(() => import("@/pages/calendar/CalendarPage").then((m) => ({ default: m.CalendarPage })));

export function App() {
  const [qc] = useState(createQueryClient);
  useEffect(() => installGlobalHandlers(), []);
  return (
    <ErrorBoundary fallback={(reset) => <ErrorPage onRetry={reset} />}>
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
