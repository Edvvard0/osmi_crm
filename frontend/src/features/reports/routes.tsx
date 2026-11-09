import { type ReactNode, Suspense, lazy } from "react";

import type { Role } from "@/shared/api/types";
import { Loading } from "@/shared/ui/ui";

const ReportsPage = lazy(() => import("./ReportsPage").then((m) => ({ default: m.ReportsPage })));
const PayrollPage = lazy(() => import("./PayrollPage").then((m) => ({ default: m.PayrollPage })));
const EarningsPage = lazy(() => import("./EarningsPage").then((m) => ({ default: m.EarningsPage })));
const LocationReportPage = lazy(() => import("./LocationReportPage").then((m) => ({ default: m.LocationReportPage })));
const MechanicActivityPage = lazy(() => import("./MechanicActivityPage").then((m) => ({ default: m.MechanicActivityPage })));

const wrap = (node: ReactNode): ReactNode => <Suspense fallback={<Loading />}>{node}</Suspense>;

export const routes: { path: string; roles: Role[]; element: ReactNode }[] = [
  { path: "reports", roles: ["director"], element: wrap(<ReportsPage />) },
  { path: "payroll", roles: ["director"], element: wrap(<PayrollPage />) },
  { path: "earnings", roles: ["mechanic"], element: wrap(<EarningsPage />) },
  { path: "location-report", roles: ["manager", "director"], element: wrap(<LocationReportPage />) },
  { path: "mechanics/:id", roles: ["manager", "director"], element: wrap(<MechanicActivityPage />) },
];
