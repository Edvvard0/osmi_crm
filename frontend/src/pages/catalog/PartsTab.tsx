import { type FormEvent, useState } from "react";

import { PAGE_SIZE, useCreatePart, useParts, useUpdatePart } from "@/features/catalog/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { PART_DEPARTMENT_LABELS, PART_UNIT_LABELS, type Part, type PartDepartment, type PartUnit } from "@/shared/api/types";
import { formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Checkbox, Dialog, Input, Loading, Select } from "@/shared/ui/ui";

import { ActiveBadge, FormActions, FormError, Pager, ResponsiveList, uniqueMessage, useDebounced } from "./common";

const DEPTS = Object.keys(PART_DEPARTMENT_LABELS) as PartDepartment[];
const UNITS = Object.keys(PART_UNIT_LABELS) as PartUnit[];

/** Справочник запчастей и материалов (без остатков). canEdit=false — режим менеджера. */
export function PartsTab({ canEdit }: { canEdit: boolean }) {
  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput.trim());
  const [dept, setDept] = useState<"" | PartDepartment>("");
  const [offset, setOffset] = useState(0);
  const [dlg, setDlg] = useState<Part | "new" | null>(null);
  const toast = useToast();
  const q = useParts({ search, department: dept }, offset);
  const items = q.data?.items ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <Input
            id="part-search"
            label="Поиск"
            type="search"
            placeholder="Артикул, название или бренд"
            value={searchInput}
            onChange={(e) => {
              setSearchInput(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <div className="w-full sm:w-48">
          <Select
            id="part-flt-dept"
            label="Отдел"
            value={dept}
            onChange={(e) => {
              setDept(e.target.value as "" | PartDepartment);
              setOffset(0);
            }}
          >
            <option value="">Все отделы</option>
            {DEPTS.map((d) => (
              <option key={d} value={d}>{PART_DEPARTMENT_LABELS[d]}</option>
            ))}
          </Select>
        </div>
        {canEdit && <Button onClick={() => setDlg("new")}>+ Позиция</Button>}
      </div>
      {q.isError && <Alert>{toAppError(q.error).message}</Alert>}
      {q.isLoading && <Loading />}
      {q.data && items.length === 0 && <p className="py-8 text-center text-sm text-muted">Позиций не найдено</p>}
      {items.length > 0 && (
        <>
          <ResponsiveList
            items={items}
            id={(p) => p.id}
            head={["Артикул", "Название", "Бренд", "Ед.", "Отдел", "Цена продажи", "Статус", ...(canEdit ? [""] : [])]}
            row={(p) => [
              p.sku,
              <span key="n" className="font-medium">{p.name}</span>,
              p.brand ?? "—",
              PART_UNIT_LABELS[p.unit],
              PART_DEPARTMENT_LABELS[p.department],
              <span key="p" className="whitespace-nowrap">{formatMoney(p.sale_price)}</span>,
              <ActiveBadge key="a" active={p.is_active} />,
              ...(canEdit
                ? [
                    <Button key="e" variant="ghost" aria-label={`Изменить позицию ${p.name}`} onClick={() => setDlg(p)}>
                      Изменить
                    </Button>,
                  ]
                : []),
            ]}
            card={(p) => (
              <>
                <div className="font-medium">{p.name}</div>
                <div className="mt-1 text-sm text-muted">{p.sku}{p.brand ? ` · ${p.brand}` : ""} · {PART_DEPARTMENT_LABELS[p.department]}</div>
                <div className="mt-1 text-sm">{formatMoney(p.sale_price)} / {PART_UNIT_LABELS[p.unit]}</div>
                <div className="mt-2 flex items-center justify-between">
                  <ActiveBadge active={p.is_active} />
                  {canEdit && (
                    <Button variant="secondary" aria-label={`Изменить позицию ${p.name}`} onClick={() => setDlg(p)}>
                      Изменить
                    </Button>
                  )}
                </div>
              </>
            )}
          />
          <Pager offset={offset} size={PAGE_SIZE} total={q.data?.total ?? 0} onChange={setOffset} />
        </>
      )}
      {dlg && (
        <PartDialog
          part={dlg === "new" ? undefined : dlg}
          onClose={() => setDlg(null)}
          onSaved={() => {
            setDlg(null);
            toast.push("success", "Сохранено");
          }}
        />
      )}
    </div>
  );
}

function PartDialog({ part, onClose, onSaved }: { part?: Part; onClose: () => void; onSaved: () => void }) {
  const create = useCreatePart();
  const update = useUpdatePart(part?.id ?? "");
  const [sku, setSku] = useState(part?.sku ?? "");
  const [name, setName] = useState(part?.name ?? "");
  const [brand, setBrand] = useState(part?.brand ?? "");
  const [barcode, setBarcode] = useState(part?.barcode ?? "");
  const [unit, setUnit] = useState<PartUnit>(part?.unit ?? "pcs");
  const [department, setDepartment] = useState<PartDepartment>(part?.department ?? "both");
  const [price, setPrice] = useState(toInput(part?.sale_price));
  const [active, setActive] = useState(part?.is_active ?? true);
  const [le, setLe] = useState<Record<string, string>>({});
  const m = part ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;
  // Дубль может быть и по артикулу, и по штрихкоду: поле определяем по ответу сервера.
  const dupBarcode = err?.fields.barcode !== undefined;

  function submit(e: FormEvent) {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!part && !sku.trim()) x.sku = "Обязательное поле";
    if (!name.trim()) x.name = "Обязательное поле";
    const p = parseDecimal(price);
    if (p === null) x.sale_price = "Цена: число не меньше 0, до двух знаков после запятой";
    setLe(x);
    if (Object.keys(x).length || p === null) return;
    const body = { name: name.trim(), brand: brand.trim() || null, barcode: barcode.trim() || null, unit, department, sale_price: p };
    if (part) update.mutate({ ...body, is_active: active }, { onSuccess: onSaved });
    else create.mutate({ ...body, sku: sku.trim() }, { onSuccess: onSaved });
  }

  return (
    <Dialog open title={part ? "Позиция" : "Новая позиция"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Input
          id="part-sku"
          label="Артикул"
          value={sku}
          readOnly={!!part}
          onChange={(e) => setSku(e.target.value)}
          error={le.sku ?? (dupBarcode ? undefined : uniqueMessage(err, "duplicate_sku")) ?? fieldMessage(err, "sku")}
        />
        <Input id="part-name" label="Название" value={name} onChange={(e) => setName(e.target.value)} error={le.name ?? fieldMessage(err, "name")} />
        <div className="grid grid-cols-2 gap-3">
          <Input id="part-brand" label="Бренд" value={brand} onChange={(e) => setBrand(e.target.value)} error={fieldMessage(err, "brand")} />
          <Input
            id="part-barcode"
            label="Штрихкод"
            value={barcode}
            onChange={(e) => setBarcode(e.target.value)}
            error={(dupBarcode ? uniqueMessage(err, "duplicate_barcode") : undefined) ?? fieldMessage(err, "barcode")}
          />
          <Select id="part-unit" label="Единица" value={unit} onChange={(e) => setUnit(e.target.value as PartUnit)}>
            {UNITS.map((u) => (
              <option key={u} value={u}>{PART_UNIT_LABELS[u]}</option>
            ))}
          </Select>
          <Select id="part-dept" label="Отдел позиции" value={department} onChange={(e) => setDepartment(e.target.value as PartDepartment)}>
            {DEPTS.map((d) => (
              <option key={d} value={d}>{PART_DEPARTMENT_LABELS[d]}</option>
            ))}
          </Select>
        </div>
        <Input id="part-price" label="Цена продажи, ₽" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} error={le.sale_price ?? fieldMessage(err, "sale_price")} />
        {part && <Checkbox label="Активна" checked={active} onChange={(e) => setActive(e.target.checked)} />}
        <FormError err={err} />
        <FormActions pending={m.isPending} onCancel={onClose} />
      </form>
    </Dialog>
  );
}
