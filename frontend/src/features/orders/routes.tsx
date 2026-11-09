import { type ReactNode, Suspense, lazy } from "react";

import { Loading } from "@/shared/ui/ui";

interface FeatureRoute {
  path: string;
  roles: Array<"mechanic" | "manager" | "director">;
  element: ReactNode;
}

const OrdersPage = lazy(() => import("./OrdersPage").then((m) => ({ default: m.OrdersPage })));
const OrderPage = lazy(() => import("./OrderPage").then((m) => ({ default: m.OrderPage })));
const OrderWizardPage = lazy(() => import("./OrderWizardPage").then((m) => ({ default: m.OrderWizardPage })));
const OrderPrintPage = lazy(() => import("./OrderPrintPage").then((m) => ({ default: m.OrderPrintPage })));
const TodayPage = lazy(() => import("./ManagerHome").then((m) => ({ default: m.TodayPage })));

const wrap = (el: ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;
const staff: FeatureRoute["roles"] = ["manager", "director"];

export const routes: FeatureRoute[] = [
  { path: "orders", roles: staff, element: wrap(<OrdersPage />) },
  { path: "orders/new", roles: staff, element: wrap(<OrderWizardPage />) },
  { path: "orders/:id", roles: staff, element: wrap(<OrderPage />) },
  { path: "orders/:id/print", roles: staff, element: wrap(<OrderPrintPage />) },
  { path: "today", roles: staff, element: wrap(<TodayPage />) },
];
