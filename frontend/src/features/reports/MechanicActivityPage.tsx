import { Link, useParams } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { useLocations } from "@/features/locations/api";
import { Skeleton } from "@/features/orders/ui";
import { useUserById } from "@/features/users/api";
import { toAppError } from "@/shared/api/errors";
import { ROLE_LABELS } from "@/shared/api/types";

import { ActivityPanel, rangeDates } from "./ActivityPanel";
import { useActivityHeatmap } from "./api";
import { QueryError } from "./filters";
import { useToday } from "./lib";

function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-3 py-10 text-center">
      <h1 className="text-xl font-semibold">Сотрудник не найден</h1>
      <p className="text-sm text-muted">Такого сотрудника нет или он работает не на ваших точках.</p>
      <Link to="/location-report" className="inline-block text-sm underline underline-offset-2">К отчёту точки</Link>
    </div>
  );
}

const isNotFound = (e: unknown) => {
  if (!e) return false;
  const s = toAppError(e).status;
  return s === 404 || s === 403;
};

/**
 * MG-17: рабочие дни сотрудника. Без зарплаты, ставок и данных учётной записи.
 * Имя берётся из карты активности (`ActivityHeatmap.user`): `GET /users/{id}` доступен только
 * руководителю, поэтому должность, точки и Telegram показываются лишь ему.
 */
export function MechanicActivityPage() {
  const { id = "" } = useParams();
  const me = useMe();
  const isDirector = me.role === "director";
  const today = useToday();
  const user = useUserById(id, isDirector);
  const locations = useLocations();
  // Тот же ключ, что у карты в ActivityPanel: запрос выполняется один раз.
  const { from, to } = rangeDates("12m", today);
  const heat = useActivityHeatmap(id, from, to);

  if (isNotFound(heat.error) || (isDirector && isNotFound(user.error))) return <NotFound />;
  if (heat.error && !heat.data) return <div className="mx-auto max-w-3xl"><QueryError error={heat.error} onRetry={() => void heat.refetch()} /></div>;
  if (!heat.data) return <div className="mx-auto max-w-3xl"><Skeleton lines={4} /></div>;

  const u = user.data;
  const names = u ? (locations.data ?? []).filter((l) => u.location_ids.includes(l.id)).map((l) => l.name) : [];

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <h1 className="break-words text-xl font-semibold">{u?.full_name ?? heat.data.user.full_name}</h1>
        {u && (
          <dl className="mt-2 space-y-1 text-sm">
            <div className="flex flex-wrap gap-x-2"><dt className="text-muted">Должность:</dt><dd>{ROLE_LABELS[u.role]}</dd></div>
            {names.length > 0 && <div className="flex flex-wrap gap-x-2"><dt className="text-muted">Точки:</dt><dd className="break-words">{names.join(", ")}</dd></div>}
            {u.telegram_linked && <div><dd>Telegram подключён</dd></div>}
          </dl>
        )}
      </div>
      <section aria-label="Рабочие дни">
        <h2 className="mb-2 text-base font-semibold">Рабочие дни</h2>
        <ActivityPanel userId={id} defaultRange="12m" />
      </section>
    </div>
  );
}
