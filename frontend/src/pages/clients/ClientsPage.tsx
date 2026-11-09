import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { type ClientFilters, CLIENTS_PAGE_SIZE, useClients } from "@/features/clients/api";
import { toAppError } from "@/shared/api/errors";
import { type Client, type ClientSource, type ClientType, SOURCE_LABELS } from "@/shared/api/types";
import { Alert, Badge, Button, Input, LinkButton, Loading, Select, Table, Td, Th } from "@/shared/ui/ui";

export function ClientName({ c }: { c: Client }) {
  return (
    <>
      <span className="font-medium">{c.full_name}</span>
      {c.company_name && <span className="block text-xs text-muted">{c.company_name}</span>}
    </>
  );
}

/** MG-08 «Клиенты» */
export function ClientsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<ClientFilters>({ search: "", client_type: "", source: "", archived: false, offset: 0 });
  const q = useClients(filters);

  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f.search === searchInput.trim() ? f : { ...f, search: searchInput.trim(), offset: 0 })), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const set = (patch: Partial<ClientFilters>) => setFilters((f) => ({ ...f, ...patch, offset: 0 }));
  const items = q.data?.items ?? [];
  const total = q.data?.total ?? 0;
  const filtered = !!(filters.search || filters.client_type || filters.source || filters.archived);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Клиенты</h1>
        <LinkButton to="/clients/new">+ Новый клиент</LinkButton>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input label="Поиск" type="search" placeholder="ФИО, телефон, госномер, VIN" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        <Select label="Тип" value={filters.client_type} onChange={(e) => set({ client_type: e.target.value as "" | ClientType })}>
          <option value="">Все</option>
          <option value="person">Физлицо</option>
          <option value="company">Компания</option>
        </Select>
        <Select label="Источник" value={filters.source} onChange={(e) => set({ source: e.target.value as "" | ClientSource })}>
          <option value="">Все источники</option>
          {(Object.keys(SOURCE_LABELS) as ClientSource[]).map((s) => (
            <option key={s} value={s}>{SOURCE_LABELS[s]}</option>
          ))}
        </Select>
        <Select label="Архив" value={String(filters.archived)} onChange={(e) => set({ archived: e.target.value === "true" })}>
          <option value="false">Активные</option>
          <option value="true">Архивные</option>
        </Select>
      </div>

      {q.isError && <Alert>{toAppError(q.error).message}</Alert>}
      {q.isLoading && <Loading />}
      {q.data && items.length === 0 &&
        (filtered ? (
          <p className="py-8 text-center text-sm text-muted">Ничего не найдено</p>
        ) : (
          <div className="space-y-3 py-8 text-center">
            <p className="text-sm text-muted">Клиентов пока нет</p>
            <LinkButton to="/clients/new">+ Новый клиент</LinkButton>
          </div>
        ))}

      {items.length > 0 && (
        <>
          <div className="hidden md:block">
            <Table>
              <thead>
                <tr>
                  <Th>Клиент</Th>
                  <Th>Телефон</Th>
                  <Th>Авто</Th>
                  <Th>Источник</Th>
                  <Th>Скидка</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => (
                  <tr key={c.id}>
                    <Td>
                      <Link className="underline-offset-2 hover:underline" to={`/clients/${encodeURIComponent(c.id)}`}><ClientName c={c} /></Link>
                      {c.archived_at && <span className="ml-2"><Badge tone="warning">В архиве</Badge></span>}
                    </Td>
                    <Td>{c.phone}</Td>
                    <Td>{c.vehicles_count}</Td>
                    <Td>{c.source ? SOURCE_LABELS[c.source] : "—"}</Td>
                    <Td>{c.discount_percent}%</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <ul className="space-y-2 md:hidden">
            {items.map((c) => (
              <li key={c.id} className="rounded-lg border border-border bg-surface p-3">
                <Link to={`/clients/${encodeURIComponent(c.id)}`} className="block"><ClientName c={c} /></Link>
                <div className="mt-1 text-sm text-muted">{c.phone}</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
                  <span>Авто: {c.vehicles_count}</span>
                  {c.discount_percent > 0 && <span>Скидка {c.discount_percent}%</span>}
                  {c.archived_at && <Badge tone="warning">В архиве</Badge>}
                </div>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between text-sm text-muted">
            <span>
              {filters.offset + 1}–{Math.min(filters.offset + CLIENTS_PAGE_SIZE, total)} из {total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={filters.offset === 0} onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, f.offset - CLIENTS_PAGE_SIZE) }))}>Назад</Button>
              <Button variant="secondary" disabled={filters.offset + CLIENTS_PAGE_SIZE >= total} onClick={() => setFilters((f) => ({ ...f, offset: f.offset + CLIENTS_PAGE_SIZE }))}>Далее</Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
