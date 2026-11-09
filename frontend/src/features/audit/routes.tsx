import { type ReactNode, Suspense, lazy } from "react";

import { Loading } from "@/shared/ui/ui";

const AuditPage = lazy(() => import("./AuditPage").then((m) => ({ default: m.AuditPage })));
const SystemSettingsPage = lazy(() => import("./SystemSettingsPage").then((m) => ({ default: m.SystemSettingsPage })));

const wrap = (el: ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

export const routes = [
  { path: "audit", roles: ["director"] as Array<"director">, element: wrap(<AuditPage />) },
  { path: "system-settings", roles: ["director"] as Array<"director">, element: wrap(<SystemSettingsPage />) },
];
