import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type UserFilters, PAGE_SIZE, useUsers } from "@/features/users/api";
import { useLocations } from "@/features/locations/api";
import { toAppError } from "@/shared/api/errors";
import { ROLE_LABELS, type Role, type User } from "@/shared/api/types";
import { Alert, Badge, Button, Input, LinkButton, Loading, Select, Table, Td, Th } from "@/shared/ui/ui";

export function StatusBadge({ active }: { active: boolean }) {
  return <Badge tone={active ? "success" : "danger"}>{active ? "Активен" : "Заблокирован"}</Badge>;
}

/** D-04 «Сотрудники» */
export function UsersPage() {
  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<UserFilters>({ search: "", role: "", location_id: "", is_active: "", offset: 0 });
  const locs = useLocations();
  const q = useUsers(filters);

  // Поиск с задержкой, чтобы не слать запрос на каждую букву.
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f.search === searchInput.trim() ? f : { ...f, search: searchInput.trim(), offset: 0 })), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const locName = (id: string) => locs.data?.find((l) => l.id === id)?.name ?? "—";
  const names = (u: User) => (u.location_ids.length ? u.location_ids.map(locName).join(", ") : "—");
  const set = (patch: Partial<UserFilters>) => setFilters((f) => ({ ...f, ...patch, offset: 0 }));
  const items = q.data?.items ?? [];
  const total = q.data?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Сотрудники</h1>
        <LinkButton to="/users/new">+ Новый сотрудник</LinkButton>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input label="Поиск" type="search" placeholder="ФИО или логин" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        <Select label="Роль" value={filters.role} onChange={(e) => set({ role: e.target.value as "" | Role })}>
          <option value="">Все роли</option>
          {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
          ))}
        </Select>
        <Select label="Точка" value={filters.location_id} onChange={(e) => set({ location_id: e.target.value })}>
          <option value="">Все точки</option>
          {(locs.data ?? []).map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </Select>
        <Select label="Статус" value={filters.is_active} onChange={(e) => set({ is_active: e.target.value as UserFilters["is_active"] })}>
          <option value="">Все</option>
          <option value="true">Активные</option>
          <option value="false">Заблокированные</option>
        </Select>
      </div>

      {q.isError && <Alert>{toAppError(q.error).message}</Alert>}
      {q.isLoading && <Loading />}
      {q.data && items.length === 0 && (
        <p className="py-8 text-center text-sm text-muted">Сотрудников не найдено</p>
      )}

      {items.length > 0 && (
        <>
          {/* Desktop: таблица */}
          <div className="hidden md:block">
            <Table>
              <thead>
                <tr>
                  <Th>ФИО</Th>
                  <Th>Логин</Th>
                  <Th>Роль</Th>
                  <Th>Точки</Th>
                  <Th>Статус</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((u) => (
                  <tr key={u.id}>
                    <Td>
                      <Link className="font-medium underline-offset-2 hover:underline" to={`/users/${u.id}`}>{u.full_name}</Link>
                    </Td>
                    <Td>{u.login}</Td>
                    <Td>{ROLE_LABELS[u.role]}</Td>
                    <Td>{names(u)}</Td>
                    <Td><StatusBadge active={u.is_active} /></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          {/* Mobile: карточки */}
          <ul className="space-y-2 md:hidden">
            {items.map((u) => (
              <li key={u.id} className="rounded-lg border border-border bg-surface p-3">
                <Link to={`/users/${u.id}`} className="font-medium">{u.full_name}</Link>
                <div className="mt-1 text-sm text-muted">{u.login} · {ROLE_LABELS[u.role]}</div>
                <div className="mt-1 text-sm text-muted">{names(u)}</div>
                <div className="mt-2"><StatusBadge active={u.is_active} /></div>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between text-sm text-muted">
            <span>
              {filters.offset + 1}–{Math.min(filters.offset + PAGE_SIZE, total)} из {total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - PAGE_SIZE) }))}>Назад</Button>
              <Button variant="secondary" disabled={filters.offset + PAGE_SIZE >= total} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + PAGE_SIZE }))}>Далее</Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
