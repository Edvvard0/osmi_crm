import { useMe } from "@/features/auth/AuthProvider";
import { useActiveLocation } from "@/features/locations/api";
import { ROLE_LABELS, type Role } from "@/shared/api/types";
import { SystemCard } from "@/features/system/SystemCard";
import { MechanicTasksPage } from "@/features/mechanic/MechanicTasksPage";
import { ManagerHome } from "@/features/orders/ManagerHome";
import { DirectorDashboard } from "@/features/reports/DirectorDashboard";

const TITLES: Record<Role, string> = {
  mechanic: "Рабочий стол механика",
  manager: "Рабочий стол менеджера",
  director: "Рабочий стол руководителя",
};

/** Рабочий стол роли: механик — задачи, менеджер — «Сегодня», директор — дашборд показателей. */
export function DashboardPage() {
  const me = useMe();
  const { current, value } = useActiveLocation();
  if (me.role === "mechanic") return <MechanicTasksPage />;
  return (
    <div>
      <h1 className="text-xl font-semibold">{TITLES[me.role]}</h1>
      <p className="mt-2 text-sm text-muted">
        {me.full_name} · {ROLE_LABELS[me.role]}
        {value === "all" ? " · Все точки" : current ? ` · ${current.name}` : ""}
      </p>
      {me.role === "director" ? <DirectorDashboard /> : <ManagerHome />}
      {me.role === "director" && <SystemCard />}
    </div>
  );
}
