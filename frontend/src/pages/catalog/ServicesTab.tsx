import clsx from "clsx";
import { type FormEvent, useMemo, useState } from "react";
import { Pencil } from "lucide-react";

import {
  PAGE_SIZE,
  type ServiceInput,
  useAllServices,
  useCategories,
  useCreateCategory,
  useCreateService,
  useServices,
  useUpdateCategory,
  useUpdateService,
} from "@/features/catalog/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import {
  type Category,
  DEPARTMENT_LABELS,
  type Department,
  SERVICE_UNIT_LABELS,
  type Service,
  type ServiceUnit,
} from "@/shared/api/types";
import { formatHours, formatMoney, parseDecimal, toInput } from "@/shared/lib/money";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Checkbox, Dialog, Input, Loading, Select, Textarea } from "@/shared/ui/ui";

import { ActiveBadge, FormActions, FormError, Pager, ResponsiveList, uniqueMessage, useDebounced } from "./common";

const DEPTS = Object.keys(DEPARTMENT_LABELS) as Department[];
const UNITS = Object.keys(SERVICE_UNIT_LABELS) as ServiceUnit[];

/** Услуги: слева дерево категорий, справа таблица. canEdit=false — режим менеджера (просмотр цен своей точки). */
export function ServicesTab({ canEdit, locationId }: { canEdit: boolean; locationId?: string }) {
  const [dept, setDept] = useState<"" | Department>("");
  const [cat, setCat] = useState<string>("");
  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput.trim());
  const [offset, setOffset] = useState(0);
  const [catDlg, setCatDlg] = useState<Category | "new" | null>(null);
  const [svcDlg, setSvcDlg] = useState<Service | "new" | null>(null);
  const toast = useToast();

  // Менеджер видит только активное и обязан передавать точку.
  const activeOnly = canEdit ? undefined : true;
  const ready = canEdit || !!locationId;
  const loc = locationId || undefined;
  const cats = useCategories({ department: dept, is_active: activeOnly });
  const all = useAllServices({ is_active: activeOnly, location_id: loc }, ready);
  const list = useServices({ search, category_id: cat, department: dept, is_active: activeOnly, location_id: loc }, offset, ready);

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of all.data ?? []) m.set(s.category_id, (m.get(s.category_id) ?? 0) + 1);
    return m;
  }, [all.data]);
  const catName = (id: string) => cats.data?.find((c) => c.id === id)?.name ?? "—";
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const priceHead = canEdit ? "Базовая цена" : "Цена";
  const price = (s: Service) => formatMoney(canEdit ? s.base_price : s.price);

  if (!ready) return <p className="py-8 text-center text-sm text-muted">Выберите точку в шапке, чтобы увидеть цены</p>;

  const groups = DEPTS.map((d) => ({ d, items: (cats.data ?? []).filter((c) => c.department === d) })).filter((g) => g.items.length);
  const totalAll = (all.data ?? []).filter((s) => !dept || s.department === dept).length;

  return (
    <div className="grid gap-4 md:grid-cols-[16rem_minmax(0,1fr)]">
      <aside aria-label="Категории" className="space-y-3">
        <Select
          id="flt-dept"
          label="Отдел"
          value={dept}
          onChange={(e) => {
            setDept(e.target.value as "" | Department);
            setCat("");
            setOffset(0);
          }}
        >
          <option value="">Все отделы</option>
          {DEPTS.map((d) => (
            <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
          ))}
        </Select>
        {cats.isError && <Alert>{toAppError(cats.error).message}</Alert>}
        <ul className="space-y-1">
          <li>
            <button
              type="button"
              aria-pressed={cat === ""}
              onClick={() => {
                setCat("");
                setOffset(0);
              }}
              className={clsx("flex min-h-10 w-full items-center justify-between rounded px-3 text-left text-sm", cat === "" ? "bg-accent text-accent-fg" : "hover:bg-border/50")}
            >
              <span>Все категории</span>
              <span>{totalAll}</span>
            </button>
          </li>
          {groups.map((g) => (
            <li key={g.d}>
              <div className="px-3 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted">{DEPARTMENT_LABELS[g.d]}</div>
              <ul className="space-y-1">
                {g.items.map((c) => (
                  <li key={c.id} className="flex items-center gap-1">
                    <button
                      type="button"
                      aria-pressed={cat === c.id}
                      onClick={() => {
                        setCat(c.id);
                        setOffset(0);
                      }}
                      className={clsx(
                        "flex min-h-10 min-w-0 flex-1 items-center justify-between gap-2 rounded px-3 text-left text-sm",
                        cat === c.id ? "bg-accent text-accent-fg" : "hover:bg-border/50",
                        !c.is_active && "opacity-60",
                      )}
                    >
                      <span className="truncate">{c.name}</span>
                      <span>{counts.get(c.id) ?? 0}</span>
                    </button>
                    {canEdit && (
                      <Button variant="ghost" className="px-2" aria-label={`Изменить категорию ${c.name}`} onClick={() => setCatDlg(c)}>
                        <Pencil aria-hidden="true" className="size-4" />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
        {canEdit && (
          <Button variant="secondary" className="w-full" onClick={() => setCatDlg("new")}>
            + Категория
          </Button>
        )}
      </aside>

      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1">
            <Input
              id="svc-search"
              label="Поиск"
              type="search"
              placeholder="Код или название"
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setOffset(0);
              }}
            />
          </div>
          {canEdit && (
            <Button onClick={() => setSvcDlg("new")} disabled={!cats.data?.length}>
              + Услуга
            </Button>
          )}
        </div>

        {list.isError && <Alert>{toAppError(list.error).message}</Alert>}
        {list.isLoading && <Loading />}
        {list.data && items.length === 0 && <p className="py-8 text-center text-sm text-muted">Услуг не найдено</p>}
        {items.length > 0 && (
          <>
            <ResponsiveList
              items={items}
              id={(s) => s.id}
              head={["Код", "Название", "Категория", "Ед.", priceHead, "Нормочасы", "Длит., мин", "Статус", ...(canEdit ? [""] : [])]}
              row={(s) => [
                s.code,
                <span key="n" className="font-medium">{s.name}</span>,
                catName(s.category_id),
                SERVICE_UNIT_LABELS[s.unit],
                <span key="p" className="whitespace-nowrap">{price(s)}</span>,
                formatHours(s.norm_hours),
                s.duration_minutes,
                <ActiveBadge key="a" active={s.is_active} />,
                ...(canEdit
                  ? [
                      <Button key="e" variant="ghost" aria-label={`Изменить услугу ${s.name}`} onClick={() => setSvcDlg(s)}>
                        Изменить
                      </Button>,
                    ]
                  : []),
              ]}
              card={(s) => (
                <>
                  <div className="font-medium">{s.name}</div>
                  <div className="mt-1 text-sm text-muted">{s.code} · {catName(s.category_id)}</div>
                  <div className="mt-1 text-sm">
                    {price(s)} / {SERVICE_UNIT_LABELS[s.unit]} · {formatHours(s.norm_hours)} · {s.duration_minutes} мин
                  </div>
                  <div className="mt-2 flex items-center justify-between">
                    <ActiveBadge active={s.is_active} />
                    {canEdit && (
                      <Button variant="secondary" aria-label={`Изменить услугу ${s.name}`} onClick={() => setSvcDlg(s)}>
                        Изменить
                      </Button>
                    )}
                  </div>
                </>
              )}
            />
            <Pager offset={offset} size={PAGE_SIZE} total={total} onChange={setOffset} />
          </>
        )}
      </div>

      {catDlg && (
        <CategoryDialog
          cat={catDlg === "new" ? undefined : catDlg}
          defaultDept={dept || "service"}
          onClose={() => setCatDlg(null)}
          onSaved={() => {
            setCatDlg(null);
            toast.push("success", "Сохранено");
          }}
        />
      )}
      {svcDlg && (
        <ServiceDialog
          svc={svcDlg === "new" ? undefined : svcDlg}
          categories={cats.data ?? []}
          defaultCat={cat}
          onClose={() => setSvcDlg(null)}
          onSaved={() => {
            setSvcDlg(null);
            toast.push("success", "Сохранено");
          }}
        />
      )}
    </div>
  );
}

function CategoryDialog({ cat, defaultDept, onClose, onSaved }: { cat?: Category; defaultDept: Department; onClose: () => void; onSaved: () => void }) {
  const create = useCreateCategory();
  const update = useUpdateCategory(cat?.id ?? "");
  const [name, setName] = useState(cat?.name ?? "");
  const [department, setDepartment] = useState<Department>(cat?.department ?? defaultDept);
  const [sort, setSort] = useState(String(cat?.sort_order ?? 0));
  const [active, setActive] = useState(cat?.is_active ?? true);
  const [le, setLe] = useState<Record<string, string>>({});
  const m = cat ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!name.trim()) x.name = "Обязательное поле";
    const so = Number(sort);
    if (!/^\d+$/.test(sort.trim()) || !Number.isSafeInteger(so)) x.sort_order = "Порядок: целое число не меньше 0";
    setLe(x);
    if (Object.keys(x).length) return;
    if (cat) update.mutate({ name: name.trim(), sort_order: so, is_active: active }, { onSuccess: onSaved });
    else create.mutate({ name: name.trim(), department, sort_order: so }, { onSuccess: onSaved });
  }

  return (
    <Dialog open title={cat ? "Категория" : "Новая категория"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Input
          id="cat-name"
          label="Название"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={le.name ?? uniqueMessage(err, "duplicate_category_name") ?? fieldMessage(err, "name")}
        />
        <Select id="cat-dept" label="Отдел категории" value={department} disabled={!!cat} onChange={(e) => setDepartment(e.target.value as Department)}>
          {DEPTS.map((d) => (
            <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
          ))}
        </Select>
        <Input id="cat-sort" label="Порядок" inputMode="numeric" value={sort} onChange={(e) => setSort(e.target.value)} error={le.sort_order ?? fieldMessage(err, "sort_order")} />
        {cat && <Checkbox label="Активна" checked={active} onChange={(e) => setActive(e.target.checked)} />}
        <FormError err={err} />
        <FormActions pending={m.isPending} onCancel={onClose} />
      </form>
    </Dialog>
  );
}

function ServiceDialog({
  svc,
  categories,
  defaultCat,
  onClose,
  onSaved,
}: {
  svc?: Service;
  categories: Category[];
  defaultCat: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const create = useCreateService();
  const update = useUpdateService(svc?.id ?? "");
  const [categoryId, setCategoryId] = useState(svc?.category_id ?? (defaultCat || categories[0]?.id || ""));
  const [code, setCode] = useState(svc?.code ?? "");
  const [name, setName] = useState(svc?.name ?? "");
  const [description, setDescription] = useState(svc?.description ?? "");
  const [unit, setUnit] = useState<ServiceUnit>(svc?.unit ?? "pcs");
  const [basePrice, setBasePrice] = useState(toInput(svc?.base_price));
  const [normHours, setNormHours] = useState(toInput(svc?.norm_hours));
  const [duration, setDuration] = useState(String(svc?.duration_minutes ?? 60));
  const [active, setActive] = useState(svc?.is_active ?? true);
  const [le, setLe] = useState<Record<string, string>>({});
  const m = svc ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!svc && !categoryId) x.category_id = "Обязательное поле";
    if (!svc && !code.trim()) x.code = "Обязательное поле";
    if (!name.trim()) x.name = "Обязательное поле";
    const price = parseDecimal(basePrice);
    if (price === null) x.base_price = "Цена: число не меньше 0, до двух знаков после запятой";
    const hours = normHours.trim() ? parseDecimal(normHours) : null;
    if (normHours.trim() && hours === null) x.norm_hours = "Нормочасы: число не меньше 0, до двух знаков после запятой";
    const dur = Number(duration);
    if (!/^\d+$/.test(duration.trim()) || !Number.isSafeInteger(dur) || dur < 1) x.duration_minutes = "Длительность: целое число минут, не меньше 1";
    setLe(x);
    if (Object.keys(x).length || price === null) return;
    const body: ServiceInput = {
      name: name.trim(),
      description: description.trim() || null,
      unit,
      base_price: price,
      norm_hours: hours,
      duration_minutes: dur,
    };
    if (svc) update.mutate({ ...body, is_active: active }, { onSuccess: onSaved });
    else create.mutate({ ...body, category_id: categoryId, code: code.trim() }, { onSuccess: onSaved });
  }

  return (
    <Dialog open title={svc ? "Услуга" : "Новая услуга"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Select id="svc-cat" label="Категория" value={categoryId} disabled={!!svc} onChange={(e) => setCategoryId(e.target.value)} error={le.category_id ?? fieldMessage(err, "category_id")}>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name} ({DEPARTMENT_LABELS[c.department]})</option>
          ))}
        </Select>
        <Input
          id="svc-code"
          label="Код"
          value={code}
          readOnly={!!svc}
          onChange={(e) => setCode(e.target.value)}
          error={le.code ?? uniqueMessage(err, "duplicate_service_code") ?? fieldMessage(err, "code")}
        />
        <Input id="svc-name" label="Название" value={name} onChange={(e) => setName(e.target.value)} error={le.name ?? fieldMessage(err, "name")} />
        <Textarea id="svc-desc" label="Описание" value={description} onChange={(e) => setDescription(e.target.value)} error={fieldMessage(err, "description")} />
        <div className="grid grid-cols-2 gap-3">
          <Select id="svc-unit" label="Единица" value={unit} onChange={(e) => setUnit(e.target.value as ServiceUnit)}>
            {UNITS.map((u) => (
              <option key={u} value={u}>{SERVICE_UNIT_LABELS[u]}</option>
            ))}
          </Select>
          <Input id="svc-price" label="Базовая цена, ₽" inputMode="decimal" value={basePrice} onChange={(e) => setBasePrice(e.target.value)} error={le.base_price ?? fieldMessage(err, "base_price")} />
          <Input id="svc-hours" label="Нормочасы" inputMode="decimal" value={normHours} onChange={(e) => setNormHours(e.target.value)} error={le.norm_hours ?? fieldMessage(err, "norm_hours")} />
          <Input id="svc-dur" label="Длительность, мин" inputMode="numeric" value={duration} onChange={(e) => setDuration(e.target.value)} error={le.duration_minutes ?? fieldMessage(err, "duration_minutes")} />
        </div>
        {svc && <Checkbox label="Активна" checked={active} onChange={(e) => setActive(e.target.checked)} />}
        <FormError err={err} />
        <FormActions pending={m.isPending} onCancel={onClose} />
      </form>
    </Dialog>
  );
}
