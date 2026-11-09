import clsx from "clsx";
import { useState } from "react";

import { fieldMessage, toAppError } from "@/shared/api/errors";
import { Modal } from "@/shared/ui/modal";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Table, Td, Textarea, Th } from "@/shared/ui/ui";

import { loadAllStocked, useInventoryCommit } from "./api";
import { diffQty, fmtQty, parseQtyOrZero, qtyEq, toQtyInput, unitLabel } from "./format";
import type { StockBalance } from "./types";

interface Row { b: StockBalance; actual: string }

/** Инвентаризация: загрузить остатки → ввести фактические → подсветить расхождения → провести. */
export function InventoryTab({ locationId }: { locationId: string }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<{ adjusted: number; unchanged: number } | null>(null);
  const commit = useInventoryCommit();
  const toast = useToast();
  const err = commit.error ? toAppError(commit.error) : null;

  async function load() {
    setLoading(true);
    setLoadError(null);
    setResult(null);
    commit.reset();
    try {
      const items = await loadAllStocked(locationId);
      setRows(items.map((b) => ({ b, actual: toQtyInput(b.quantity) })));
    } catch (e) {
      setLoadError(toAppError(e).message);
    } finally {
      setLoading(false);
    }
  }

  const parsed = (rows ?? []).map((r) => ({ r, actual: parseQtyOrZero(r.actual) }));
  const invalidCount = parsed.filter((p) => p.actual === null).length;
  const changed = parsed.filter((p) => p.actual !== null && !qtyEq(p.actual, p.r.b.quantity));

  function submit() {
    if (!rows || changed.length === 0 || invalidCount > 0) return;
    commit.mutate(
      {
        location_id: locationId,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
        items: changed.map((p) => ({ part_id: p.r.b.part.id, expected_quantity: p.r.b.quantity, actual_quantity: p.actual as string })),
      },
      {
        onSuccess: (res) => {
          setConfirm(false);
          setResult({ adjusted: res.movements.length, unchanged: res.skipped + (rows.length - changed.length) });
          setRows(null);
          setComment("");
          toast.push("success", "Инвентаризация проведена");
        },
        onError: () => setConfirm(false),
      },
    );
  }

  if (result) {
    return (
      <div className="space-y-3">
        <p role="status" className="rounded border border-border bg-surface px-3 py-3 text-sm">
          Инвентаризация проведена: скорректировано {result.adjusted}, без изменений {result.unchanged}.
        </p>
        <Button variant="secondary" onClick={() => void load()}>Начать заново</Button>
      </div>
    );
  }

  if (!rows) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">Загрузите текущие остатки точки, введите фактическое количество и проведите корректировку.</p>
        {loadError && <Alert>{loadError}</Alert>}
        <Button onClick={() => void load()} loading={loading}>Загрузить остатки</Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {err?.code === "stock_changed" && (
        <div className="flex items-center gap-2">
          <div className="flex-1"><Alert>{err.message}</Alert></div>
          <Button variant="secondary" onClick={() => void load()}>Обновить</Button>
        </div>
      )}
      {err && err.code !== "stock_changed" && err.code !== "validation_error" && <Alert>{err.message}</Alert>}
      {err?.fields.items !== undefined && <Alert>{fieldMessage(err, "items")}</Alert>}
      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">На складе пока ничего нет</p>
      ) : (
        <Table>
          <thead>
            <tr><Th>Артикул</Th><Th>Название</Th><Th>Ожидается</Th><Th>Фактически</Th><Th>Разница</Th></tr>
          </thead>
          <tbody>
            {parsed.map(({ r, actual }, i) => {
              const diff = actual !== null && !qtyEq(actual, r.b.quantity);
              return (
                <tr key={r.b.part.id} className={clsx(diff && "bg-warning/10")}>
                  <Td>{r.b.part.sku}</Td>
                  <Td>{r.b.part.name}</Td>
                  <Td><span className="whitespace-nowrap">{fmtQty(r.b.quantity)} {unitLabel(r.b.part.unit)}</span></Td>
                  <Td>
                    <input
                      aria-label={`Фактически: ${r.b.part.name}`}
                      inputMode="decimal"
                      value={r.actual}
                      aria-invalid={actual === null}
                      onChange={(e) => setRows(rows.map((x, k) => (k === i ? { ...x, actual: e.target.value } : x)))}
                      className={clsx("min-h-9 w-28 rounded border bg-surface px-2 text-fg", actual === null ? "border-danger" : "border-border")}
                    />
                  </Td>
                  <Td>
                    {actual !== null && diff ? <span className="whitespace-nowrap font-medium">{diffQty(actual, r.b.quantity)}</span> : "—"}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted">
          Расхождений: {changed.length}{invalidCount > 0 && ` · некорректных значений: ${invalidCount}`}
        </span>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => void load()} loading={loading}>Перезагрузить</Button>
          <Button onClick={() => setConfirm(true)} disabled={changed.length === 0 || invalidCount > 0}>Провести</Button>
        </div>
      </div>
      {confirm && (
        <Modal title="Провести инвентаризацию" onClose={() => setConfirm(false)}>
          <div className="space-y-3">
            <p className="text-sm">Будет скорректировано позиций: {changed.length}. Без изменений: {rows.length - changed.length}.</p>
            <Textarea id="inv-comment" label="Комментарий (необязательно)" value={comment} onChange={(e) => setComment(e.target.value)} error={fieldMessage(err, "comment")} />
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirm(false)}>Отмена</Button>
              <Button onClick={submit} loading={commit.isPending}>Подтвердить</Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
