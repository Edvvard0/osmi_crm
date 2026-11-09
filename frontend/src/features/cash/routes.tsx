import { type ReactNode, Suspense, lazy } from "react";

import type { Role } from "@/shared/api/types";
import { Loading } from "@/shared/ui/ui";

const CashPage = lazy(() => import("./CashPage").then((m) => ({ default: m.CashPage })));

export const routes: { path: string; roles: Role[]; element: ReactNode }[] = [
  {
    path: "cash",
    roles: ["manager", "director"],
    element: (
      <Suspense fallback={<Loading />}>
        <CashPage />
      </Suspense>
    ),
  },
];
