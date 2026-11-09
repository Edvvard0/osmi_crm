import { useMe } from "@/features/auth/AuthProvider";
import { useActiveLocation } from "@/features/locations/api";
import { ROLE_LABELS, type Role } from "@/shared/api/types";
import { Badge } from "@/shared/ui/ui";

const TITLES: Record<Role, string> = {
  mechanic: "Рабочий стол механика",
  manager: "Рабочий стол менеджера",
  director: "Рабочий стол руководителя",
};

/** Заглушка рабочего стола роли: наполнение появится в следующих модулях. */
export function DashboardPage() {
  const me = useMe();
  const { current, value } = useActiveLocation();
  return (
    <div>
      <h1 className="text-xl font-semibold">{TITLES[me.role]}</h1>
      <p className="mt-2 text-sm text-muted">
        {me.full_name} · {ROLE_LABELS[me.role]}
        {value === "all" ? " · Все точки" : current ? ` · ${current.name}` : ""}
      </p>
      <p className="mt-4 text-sm text-muted">Разделы появятся в следующих модулях.</p>
      <div className="mt-4 flex gap-2">
        <Badge tone="success">Модуль 1</Badge>
        <Badge>Доступ и точки</Badge>
      </div>
    </div>
  );
}
