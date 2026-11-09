import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { fieldMessage, toAppError } from "@/shared/api/errors";
import { formatMoney } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Button, Input, Loading } from "@/shared/ui/ui";

import { useReceipt, useStockLocation } from "./api";
import { type Line, LinesEditor, OpError, PartPicker, addLine } from "./components";
import { lineTotal, parseDecimalOrNull, parseQty, sumMoney } from "./format";
import { LocationSelect } from "./StockPage";

/** MG-12 «Приход товара». */
export function ReceiptPage() {
  const { locationId, items, loading } = useStockLocation();
  const m = useReceipt();
  const toast = useToast();
  const nav = useNavigate();
  const [supplier, setSupplier] = useState("");
  const [doc, setDoc] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [tried, setTried] = useState(false);
  const err = m.error ? toAppError(m.error) : null;

  const total = sumMoney(
    lines.flatMap((l) => {
      const q = parseQty(l.qty);
      const c = parseDecimalOrNull(l.cost);
      return q && c ? [lineTotal(q, c)] : [];
    }),
  );
  const back = locationId ? `/stock?location_id=${encodeURIComponent(locationId)}` : "/stock";

  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    const parsed = lines.map((l) => ({ part_id: l.part.id, quantity: parseQty(l.qty), unit_cost: parseDecimalOrNull(l.cost) }));
    if (lines.length === 0 || parsed.some((p) => p.quantity === null || p.unit_cost === null)) return;
    m.mutate(
      {
        location_id: locationId,
        ...(supplier.trim() ? { supplier: supplier.trim() } : {}),
        ...(doc.trim() ? { document_number: doc.trim() } : {}),
        items: parsed as { part_id: string; quantity: string; unit_cost: string }[],
      },
      {
        onSuccess: () => {
          toast.push("success", "Приход проведён");
          nav(back);
        },
      },
    );
  }

  if (loading) return <Loading />;
  if (!locationId) return <p className="py-8 text-center text-sm text-muted">Нет доступных точек</p>;

  return (
    <form onSubmit={submit} className="max-w-3xl space-y-4" noValidate>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to={back} className="text-sm text-muted underline">← Склад</Link>
          <h1 className="text-xl font-semibold">Приход товара</h1>
        </div>
        {items.length > 1 && <LocationSelect />}
      </div>
      {items.length <= 1 && <p className="text-sm text-muted">Точка: {items[0]?.name}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Input id="receipt-supplier" label="Поставщик" value={supplier} onChange={(e) => setSupplier(e.target.value)} error={fieldMessage(err, "supplier")} />
        <Input id="receipt-doc" label="Номер накладной" value={doc} onChange={(e) => setDoc(e.target.value)} error={fieldMessage(err, "document_number")} />
      </div>
      <PartPicker onPick={(p) => setLines((ls) => addLine(ls, p))} />
      <LinesEditor lines={lines} setLines={setLines} withCost error={err} invalid={tried} />
      {err?.fields.items !== undefined && <p role="alert" className="text-sm text-danger">{fieldMessage(err, "items")}</p>}
      <OpError err={m.error} lines={lines} />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
        <div className="text-sm">
          Итого: <span className="text-lg font-semibold">{formatMoney(total)}</span>
        </div>
        <Button type="submit" loading={m.isPending} disabled={lines.length === 0}>Провести приход</Button>
      </div>
    </form>
  );
}
