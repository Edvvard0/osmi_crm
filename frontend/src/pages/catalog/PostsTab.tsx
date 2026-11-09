import { type FormEvent, useState } from "react";

import { useCreatePost, usePosts, useUpdatePost } from "@/features/catalog/api";
import { useLocations } from "@/features/locations/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { DEPARTMENT_LABELS, type Department, POST_TYPE_LABELS, type Post, type PostType } from "@/shared/api/types";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Checkbox, Dialog, Input, Loading, Select } from "@/shared/ui/ui";

import { ActiveBadge, FormActions, FormError, ResponsiveList, uniqueMessage } from "./common";

const DEPTS = Object.keys(DEPARTMENT_LABELS) as Department[];
const TYPES = Object.keys(POST_TYPE_LABELS) as PostType[];

/** Посты и боксы выбранной точки (руководитель). */
export function PostsTab() {
  const locs = useLocations();
  const locations = (locs.data ?? []).filter((l) => l.is_active);
  const [picked, setPicked] = useState("");
  const locationId = locations.some((l) => l.id === picked) ? picked : (locations[0]?.id ?? "");
  const q = usePosts(locationId);
  const [dlg, setDlg] = useState<Post | "new" | null>(null);
  const toast = useToast();
  const items = [...(q.data ?? [])].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1 sm:max-w-xs">
          <Select id="post-loc" label="Точка" value={locationId} onChange={(e) => setPicked(e.target.value)}>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </Select>
        </div>
        <Button onClick={() => setDlg("new")} disabled={!locationId}>+ Пост</Button>
      </div>
      {q.isError && <Alert>{toAppError(q.error).message}</Alert>}
      {(locs.isLoading || q.isLoading) && <Loading />}
      {q.data && items.length === 0 && <p className="py-8 text-center text-sm text-muted">На этой точке постов пока нет</p>}
      {items.length > 0 && (
        <ResponsiveList
          items={items}
          id={(p) => p.id}
          head={["Название", "Тип", "Отдел", "Порядок", "Статус", ""]}
          row={(p) => [
            <span key="n" className="font-medium">{p.name}</span>,
            POST_TYPE_LABELS[p.post_type],
            DEPARTMENT_LABELS[p.department],
            p.sort_order,
            <ActiveBadge key="a" active={p.is_active} />,
            <Button key="e" variant="ghost" aria-label={`Изменить пост ${p.name}`} onClick={() => setDlg(p)}>Изменить</Button>,
          ]}
          card={(p) => (
            <>
              <div className="font-medium">{p.name}</div>
              <div className="mt-1 text-sm text-muted">{POST_TYPE_LABELS[p.post_type]} · {DEPARTMENT_LABELS[p.department]}</div>
              <div className="mt-2 flex items-center justify-between">
                <ActiveBadge active={p.is_active} />
                <Button variant="secondary" aria-label={`Изменить пост ${p.name}`} onClick={() => setDlg(p)}>Изменить</Button>
              </div>
            </>
          )}
        />
      )}
      {dlg && (
        <PostDialog
          post={dlg === "new" ? undefined : dlg}
          locationId={locationId}
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

function PostDialog({ post, locationId, onClose, onSaved }: { post?: Post; locationId: string; onClose: () => void; onSaved: () => void }) {
  const create = useCreatePost(locationId);
  const update = useUpdatePost(post?.id ?? "");
  const [name, setName] = useState(post?.name ?? "");
  const [type, setType] = useState<PostType>(post?.post_type ?? "lift");
  const [department, setDepartment] = useState<Department>(post?.department ?? "service");
  const [sort, setSort] = useState(String(post?.sort_order ?? 0));
  const [active, setActive] = useState(post?.is_active ?? true);
  const [le, setLe] = useState<Record<string, string>>({});
  const m = post ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!name.trim()) x.name = "Обязательное поле";
    const so = Number(sort);
    if (!/^\d+$/.test(sort.trim()) || !Number.isSafeInteger(so)) x.sort_order = "Порядок: целое число не меньше 0";
    setLe(x);
    if (Object.keys(x).length) return;
    const body = { name: name.trim(), post_type: type, department, sort_order: so };
    if (post) update.mutate({ ...body, is_active: active }, { onSuccess: onSaved });
    else create.mutate(body, { onSuccess: onSaved });
  }

  return (
    <Dialog open title={post ? "Пост" : "Новый пост"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Input id="post-name" label="Название" value={name} onChange={(e) => setName(e.target.value)} error={le.name ?? uniqueMessage(err, "duplicate_post_name") ?? fieldMessage(err, "name")} />
        <Select id="post-type" label="Тип" value={type} onChange={(e) => setType(e.target.value as PostType)}>
          {TYPES.map((t) => (
            <option key={t} value={t}>{POST_TYPE_LABELS[t]}</option>
          ))}
        </Select>
        <Select id="post-dept" label="Отдел поста" value={department} onChange={(e) => setDepartment(e.target.value as Department)}>
          {DEPTS.map((d) => (
            <option key={d} value={d}>{DEPARTMENT_LABELS[d]}</option>
          ))}
        </Select>
        <Input id="post-sort" label="Порядок" inputMode="numeric" value={sort} onChange={(e) => setSort(e.target.value)} error={le.sort_order ?? fieldMessage(err, "sort_order")} />
        {post && <Checkbox label="Активен" checked={active} onChange={(e) => setActive(e.target.checked)} />}
        <FormError err={err} />
        <FormActions pending={m.isPending} onCancel={onClose} />
      </form>
    </Dialog>
  );
}
