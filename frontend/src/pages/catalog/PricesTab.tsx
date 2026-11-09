import clsx from "clsx";
import { type FormEvent, useState } from "react";

import { useAllServices, usePricesByLocation, useResetPrice, useSetPrice } from "@/features/catalog/api";
import { useLocations } from "@/features/locations/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS, type CrmLocation, type Department, type Service } from "@/shared/api/types";
import { formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Dialog, Input, Loading, Select } from "@/shared/ui/ui";

import { FormError, useDebounced } from "./common";

interface Cell { service: Service; location: CrmLocation; override: string | null }

/** Матрица «услуга × точка»: показывает базовую цену или переопределение (жирным). */
export function PricesTab() {
  const locs = useLocations();
  const locations = (locs.data ?? []).filter((l) => l.is_active);
  const services = useAllServices({});
  const prices = usePricesByLocation(locations.map((l) => l.id));
  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput.trim().toLowerCase());
  const [dept, setDept] = useState<"" | Department>("");
  const [cell, setCell] = useState<Cell | null>(null);
  const toast = useToast();

  const rows = (services.data ?? []).filter(
    (s) => (!dept || s.department === dept) && (!search || s.name.toLowerCase().includes(search) || s.code.toLowerCase().includes(search)),
  );
  const loading = locs.isLoading || services.isLoading || prices.loading;
  const error = locs.error ?? services.error ?? prices.error;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input id="prc-search" label="Поиск" type="search" placeholder="Код или название" value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
        <Select id="prc-dept" label="Отдел" value={dept} onChange={(e) => setDept(e.target.value as "" | Department)}>
          <option value="">Все отделы</option>
          {(Object.keys(DEPARTMENT_LABELS) as Department[]).map((d) => (
            <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
          ))}
        </Select>
      </div>
      <p className="text-xs text-muted">Жирным выделены цены, переопределённые для точки. Остальные берутся из базовой цены. Нажмите на цену, чтобы изменить.</p>
      {error != null && <Alert>{toAppError(error).message}</Alert>}
      {loading && <Loading />}
      {!loading && rows.length === 0 && <p className="py-8 text-center text-sm text-muted">Услуг не найдено</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th scope="col" className="sticky left-0 border-b border-border bg-surface px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted">Услуга</th>
                <th scope="col" className="border-b border-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted">Базовая</th>
                {locations.map((l) => (
                  <th key={l.id} scope="col" className="border-b border-border px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted">{l.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <th scope="row" className="sticky left-0 min-w-40 border-b border-border bg-surface px-3 py-2 text-left font-normal">
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-muted">{s.code}</div>
                  </th>
                  <td className="whitespace-nowrap border-b border-border px-3 py-2 text-muted">{formatMoney(s.base_price)}</td>
                  {locations.map((l) => {
                    const override = prices.map.get(`${s.id}:${l.id}`) ?? null;
                    return (
                      <td key={l.id} className="border-b border-border px-1 py-1">
                        <button
                          type="button"
                          aria-label={`${s.name}, ${l.name}: ${formatMoney(override ?? s.base_price)}${override ? " (своя цена)" : " (базовая)"}`}
                          onClick={() => setCell({ service: s, location: l, override })}
                          className={clsx("min-h-10 w-full whitespace-nowrap rounded px-2 text-left hover:bg-border/50", override ? "font-bold" : "text-muted")}
                        >
                          {formatMoney(override ?? s.base_price)}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cell && (
        <PriceDialog
          cell={cell}
          onClose={() => setCell(null)}
          onSaved={(text) => {
            setCell(null);
            toast.push("success", text);
          }}
        />
      )}
    </div>
  );
}

function PriceDialog({ cell, onClose, onSaved }: { cell: Cell; onClose: () => void; onSaved: (text: string) => void }) {
  const { service, location, override } = cell;
  const set = useSetPrice();
  const reset = useResetPrice();
  const [value, setValue] = useState(toInput(override ?? service.base_price));
  const [le, setLe] = useState<string>();
  const err: AppError | null = set.error ? toAppError(set.error) : reset.error ? toAppError(reset.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const p = parseDecimal(value);
    if (p === null) {
      setLe("Цена: число не меньше 0, до двух знаков после запятой");
      return;
    }
    setLe(undefined);
    set.mutate({ serviceId: service.id, locationId: location.id, price: p }, { onSuccess: () => onSaved("Цена сохранена") });
  }

  return (
    <Dialog open title={`Цена: ${service.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <p className="text-sm text-muted">
          Точка: {location.name}. Базовая цена: {formatMoney(service.base_price)}.
        </p>
        <Input id="prc-value" label="Цена на точке, ₽" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} error={le ?? fieldMessage(err, "price")} />
        <FormError err={err} />
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          {override !== null && (
            <Button
              type="button"
              variant="secondary"
              loading={reset.isPending}
              onClick={() => reset.mutate({ serviceId: service.id, locationId: location.id }, { onSuccess: () => onSaved("Возврат к базовой цене") })}
            >
              Сбросить к базовой
            </Button>
          )}
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" loading={set.isPending}>Сохранить</Button>
        </div>
      </form>
    </Dialog>
  );
}
