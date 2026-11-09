import { type FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { fieldMessage, toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Input, Loading } from "@/shared/ui/ui";

import { useSetMinQuantity, useStockItem, useStockLocation } from "./api";
import { Stat } from "./components";
import { fmtQty, parseQtyOrZero, toQtyInput, unitLabel } from "./format";
import { MovementsView } from "./MovementsView";
import { LocationSelect } from "./StockPage";

/** Карточка позиции склада: остаток, редактируемый минимум, себестоимость, история движений. */
export function PartPage() {
  const { partId = "" } = useParams();
  const { locationId, loading } = useStockLocation();
  const q = useStockItem(partId, locationId);
  const back = locationId ? `/stock?location_id=${encodeURIComponent(locationId)}` : "/stock";
  const err = q.error ? toAppError(q.error) : null;

  if (loading || q.isLoading) return <Loading />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <Link to={back} className="text-sm text-muted underline">← Склад</Link>
          <h1 className="truncate text-xl font-semibold">{q.data?.part.name ?? "Позиция"}</h1>
          {q.data && <p className="text-sm text-muted">{q.data.part.sku}{q.data.part.brand ? ` · ${q.data.part.brand}` : ""}</p>}
        </div>
        <LocationSelect />
      </div>
      {err && (
        <div className="flex items-center gap-2">
          <div className="flex-1"><Alert>{err.message}</Alert></div>
          <Button variant="secondary" onClick={() => void q.refetch()}>Повторить</Button>
        </div>
      )}
      {q.data && (
        <>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <Stat label="Остаток" value={<span className={q.data.is_low ? "text-danger" : undefined}>{fmtQty(q.data.quantity)} {unitLabel(q.data.part.unit)}</span>} />
            <Stat label="Ср. себестоимость" value={formatMoney(q.data.avg_cost)} />
            <Stat label="Цена продажи" value={formatMoney(q.data.part.sale_price)} />
            <Stat label="Стоимость остатка" value={formatMoney(q.data.stock_value)} />
          </div>
          {q.data.is_low && <Badge tone="danger">Дефицит</Badge>}
          <MinForm key={`${q.data.part.id}:${q.data.min_quantity}`} partId={partId} locationId={locationId} initial={q.data.min_quantity} />
          <section className="space-y-2">
            <h2 className="text-base font-semibold">История движений</h2>
            <MovementsView locationId={locationId} fixedPartId={partId} />
          </section>
        </>
      )}
    </div>
  );
}

function MinForm({ partId, locationId, initial }: { partId: string; locationId: string; initial: string }) {
  const m = useSetMinQuantity(partId, locationId);
  const toast = useToast();
  const [v, setV] = useState(toQtyInput(initial));
  const [le, setLe] = useState<string | undefined>();
  const err = m.error ? toAppError(m.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const p = parseQtyOrZero(v);
    if (p === null) return setLe("Минимум: число не меньше 0, до трёх знаков после запятой");
    setLe(undefined);
    m.mutate(p, { onSuccess: () => toast.push("success", "Минимум сохранён") });
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2" noValidate>
      <div className="w-48">
        <Input id="min-qty" label="Минимальный остаток" inputMode="decimal" value={v} onChange={(e) => setV(e.target.value)} error={le ?? fieldMessage(err, "min_quantity")} />
      </div>
      <Button type="submit" variant="secondary" loading={m.isPending}>Сохранить</Button>
      {err && err.code !== "validation_error" && <Alert>{err.message}</Alert>}
    </form>
  );
}
