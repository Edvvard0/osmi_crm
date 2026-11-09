import { type ReactNode, Suspense, lazy } from "react";

import { Loading } from "@/shared/ui/ui";

interface FeatureRoute { path: string; roles: Array<"mechanic" | "manager" | "director">; element: ReactNode }

const TaskPage = lazy(() => import("./TaskPage").then((m) => ({ default: m.TaskPage })));
const PartRequestPage = lazy(() => import("./PartRequestPage").then((m) => ({ default: m.PartRequestPage })));
const RecommendationPage = lazy(() => import("./RecommendationPage").then((m) => ({ default: m.RecommendationPage })));
const MyRequestsPage = lazy(() => import("./MyRequestsPage").then((m) => ({ default: m.MyRequestsPage })));
const PartRequestsPage = lazy(() => import("./PartRequestsPage").then((m) => ({ default: m.PartRequestsPage })));

const wrap = (n: ReactNode) => <Suspense fallback={<Loading />}>{n}</Suspense>;

export const routes: FeatureRoute[] = [
  { path: "tasks/:itemId", roles: ["mechanic"], element: wrap(<TaskPage />) },
  { path: "tasks/:itemId/part-request", roles: ["mechanic"], element: wrap(<PartRequestPage />) },
  { path: "tasks/:itemId/recommendation", roles: ["mechanic"], element: wrap(<RecommendationPage />) },
  { path: "requests", roles: ["mechanic"], element: wrap(<MyRequestsPage />) },
  { path: "part-requests", roles: ["manager", "director"], element: wrap(<PartRequestsPage />) },
];
