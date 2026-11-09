import { useActiveLocation } from "@/features/locations/api";

import { PartRequestsPanel } from "./PartRequestsPanel";

/** MG-11: заявки механиков на запчасти (менеджер, руководитель). */
export function PartRequestsPage() {
  const loc = useActiveLocation();
  const locationId = loc.value && loc.value !== "all" ? loc.value : undefined;
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Заявки механиков</h1>
      {loc.loading ? (
        <p role="status" className="text-sm text-muted">Загрузка…</p>
      ) : (
        <PartRequestsPanel locationId={locationId} />
      )}
    </div>
  );
}
