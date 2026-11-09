import { Link } from "react-router-dom";

import { useLocations } from "@/features/locations/api";
import { toAppError } from "@/shared/api/errors";
import type { CrmLocation } from "@/shared/api/types";
import { Alert, Badge, LinkButton, Loading, Table, Td, Th } from "@/shared/ui/ui";

function ActiveBadge({ l }: { l: CrmLocation }) {
  return <Badge tone={l.is_active ? "success" : "neutral"}>{l.is_active ? "Работает" : "Закрыта"}</Badge>;
}

/** D-06 «Точки» */
export function LocationsPage() {
  const q = useLocations();
  const items = q.data ?? [];
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Точки</h1>
        <LinkButton to="/locations/new">+ Новая точка</LinkButton>
      </div>
      {q.isError && <Alert>{toAppError(q.error).message}</Alert>}
      {q.isLoading && <Loading />}
      {q.data && items.length === 0 && <p className="py-8 text-center text-sm text-muted">Точек пока нет</p>}
      {items.length > 0 && (
        <>
          <div className="hidden md:block">
            <Table>
              <thead>
                <tr>
                  <Th>Название</Th>
                  <Th>Адрес</Th>
                  <Th>Телефон</Th>
                  <Th>Статус</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((l) => (
                  <tr key={l.id}>
                    <Td><Link className="font-medium underline-offset-2 hover:underline" to={`/locations/${l.id}`}>{l.name}</Link></Td>
                    <Td>{l.address}</Td>
                    <Td>{l.phone ?? "—"}</Td>
                    <Td><ActiveBadge l={l} /></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <ul className="space-y-2 md:hidden">
            {items.map((l) => (
              <li key={l.id} className="rounded-lg border border-border bg-surface p-3">
                <Link to={`/locations/${l.id}`} className="font-medium">{l.name}</Link>
                <div className="mt-1 text-sm text-muted">{l.address}</div>
                {l.phone && <div className="text-sm text-muted">{l.phone}</div>}
                <div className="mt-2"><ActiveBadge l={l} /></div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
