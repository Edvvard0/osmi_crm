import { lazy, Suspense } from "react";

import type { Role } from "@/shared/api/types";
import { Loading } from "@/shared/ui/ui";

// Страницы склада (модуль 8) грузятся отдельными чанками.
const StockPage = lazy(() => import("./StockPage").then((m) => ({ default: m.StockPage })));
const ReceiptPage = lazy(() => import("./ReceiptPage").then((m) => ({ default: m.ReceiptPage })));
const PartPage = lazy(() => import("./PartPage").then((m) => ({ default: m.PartPage })));

const roles: Role[] = ["manager", "director"];
const wrap = (el: React.ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

export const routes = [
  { path: "stock", roles, element: wrap(<StockPage tab="balances" />) },
  { path: "stock/movements", roles, element: wrap(<StockPage tab="movements" />) },
  { path: "stock/requests", roles, element: wrap(<StockPage tab="requests" />) },
  { path: "stock/inventory", roles, element: wrap(<StockPage tab="inventory" />) },
  { path: "stock/receipt", roles, element: wrap(<ReceiptPage />) },
  { path: "stock/:partId", roles, element: wrap(<PartPage />) },
];
