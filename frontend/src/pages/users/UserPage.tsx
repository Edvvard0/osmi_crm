import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useMe } from "@/features/auth/AuthProvider";
import { useRevokeUserSessions } from "@/features/audit/api";
import { useLocations } from "@/features/locations/api";
import { useCreateUser, useResetPassword, useUpdateUser, useUserById } from "@/features/users/api";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { ROLE_LABELS, type Role, type User } from "@/shared/api/types";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, Checkbox, Dialog, Input, LinkButton, Loading, PasswordInput, Select } from "@/shared/ui/ui";

import { StatusBadge } from "./UsersPage";

/** D-05 «Карточка сотрудника» и форма создания (/users/new) */
export function UserPage() {
  const { id } = useParams();
  const isNew = id === "new";
  const q = useUserById(id);
  if (isNew) return <UserForm />;
  if (q.isLoading) return <Loading />;
  if (q.isError || !q.data) return <Alert>{toAppError(q.error).message}</Alert>;
  return <UserForm user={q.data} />;
}

function UserForm({ user }: { user?: User }) {
  const me = useMe();
  const nav = useNavigate();
  const toast = useToast();
  const locs = useLocations();
  const create = useCreateUser();
  const update = useUpdateUser(user?.id ?? "");
  const block = useUpdateUser(user?.id ?? "", false);
  const revoke = useRevokeUserSessions(user?.id ?? "");

  const [login, setLogin] = useState("");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "manager");
  const [password, setPassword] = useState("");
  const [locIds, setLocIds] = useState<string[]>(user?.location_ids ?? []);
  const [localErr, setLocalErr] = useState<Record<string, string>>({});
  const [resetOpen, setResetOpen] = useState(false);
  const [blockOpen, setBlockOpen] = useState(false);

  const m = user ? update : create;
  const err: AppError | null = m.error ? toAppError(m.error) : null;
  const isSelf = user?.id === me.id;

  const loginErr = localErr.login ?? fieldMessage(err, "login") ?? (err?.code === "unique_violation" ? "Такой логин уже занят" : undefined);
  const nameErr = localErr.full_name ?? fieldMessage(err, "full_name");
  const passErr = localErr.password ?? fieldMessage(err, "password");
  const showAlert = err && err.code !== "validation_error" && err.code !== "unique_violation";

  function toggleLoc(lid: string) {
    setLocIds((x) => (x.includes(lid) ? x.filter((i) => i !== lid) : [...x, lid]));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const le: Record<string, string> = {};
    if (!user && !login.trim()) le.login = "Обязательное поле";
    if (!fullName.trim()) le.full_name = "Обязательное поле";
    if (!user && !password) le.password = "Обязательное поле";
    setLocalErr(le);
    if (Object.keys(le).length) return;
    if (user) {
      update.mutate({ full_name: fullName.trim(), role: isSelf ? undefined : role, location_ids: locIds }, { onSuccess: () => toast.push("success", "Сохранено") });
    } else {
      create.mutate(
        { login: login.trim(), full_name: fullName.trim(), role, password, location_ids: locIds },
        { onSuccess: (u) => nav(`/users/${u.id}`, { replace: true }) },
      );
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{user ? user.full_name : "Новый сотрудник"}</h1>
          {user && (
            <div className="mt-1 flex items-center gap-2 text-sm text-muted">
              <span>{user.login}</span>
              <StatusBadge active={user.is_active} />
              <span>Последний вход: {user.last_login_at ? new Date(user.last_login_at).toLocaleString("ru-RU") : "—"}</span>
            </div>
          )}
        </div>
        <LinkButton to="/users" variant="secondary">К списку</LinkButton>
      </div>

      <form onSubmit={submit} className="space-y-3" noValidate>
        {!user && <Input label="Логин" autoComplete="off" value={login} onChange={(e) => setLogin(e.target.value)} error={loginErr} />}
        <Input label="ФИО" value={fullName} onChange={(e) => setFullName(e.target.value)} error={nameErr} />
        <Select label="Роль" value={role} onChange={(e) => setRole(e.target.value as Role)} disabled={isSelf}>
          {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
          ))}
        </Select>
        {!user && <PasswordInput label="Начальный пароль" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} error={passErr} />}
        <fieldset className="space-y-1">
          <legend className="mb-1 text-sm text-muted">Точки</legend>
          {(locs.data ?? []).map((l) => (
            <Checkbox key={l.id} label={l.name} checked={locIds.includes(l.id)} onChange={() => toggleLoc(l.id)} />
          ))}
          {locs.data?.length === 0 && <p className="text-sm text-muted">Точек пока нет</p>}
        </fieldset>
        {showAlert && <Alert>{err.message}</Alert>}
        <Button type="submit" loading={m.isPending}>{user ? "Сохранить" : "Создать"}</Button>
      </form>

      {user && (
        <section aria-labelledby="u-access" className="space-y-3 border-t border-border pt-4">
          <h2 id="u-access" className="text-base font-semibold">Доступ</h2>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setResetOpen(true)}>Сбросить пароль</Button>
            <Button variant="secondary" loading={revoke.isPending} onClick={() => revoke.mutate(undefined, { onSuccess: () => toast.push("success", "Сессии сотрудника завершены") })}>Завершить все сессии</Button>
            {user.is_active ? (
              <Button variant="danger" disabled={isSelf} onClick={() => setBlockOpen(true)}>Заблокировать</Button>
            ) : (
              <Button variant="secondary" loading={block.isPending} onClick={() => block.mutate({ is_active: true })}>Разблокировать</Button>
            )}
          </div>
          {isSelf && <p className="text-xs text-muted">Свою учётную запись заблокировать нельзя.</p>}
          <ResetDialog userId={user.id} open={resetOpen} onClose={() => setResetOpen(false)} />
          <Dialog open={blockOpen} title="Заблокировать сотрудника?" onClose={() => setBlockOpen(false)}>
            <p className="text-sm text-muted">{user.full_name} не сможет войти, активные сессии будут завершены.</p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setBlockOpen(false)}>Отмена</Button>
              <Button variant="danger" loading={block.isPending} onClick={() => block.mutate({ is_active: false }, { onSuccess: () => setBlockOpen(false) })}>
                Заблокировать
              </Button>
            </div>
          </Dialog>
        </section>
      )}
    </div>
  );
}

function ResetDialog({ userId, open, onClose }: { userId: string; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const m = useResetPassword(userId);
  const [pw, setPw] = useState("");
  const err = m.error ? toAppError(m.error) : null;
  const fe = fieldMessage(err, "new_password");

  function close() {
    setPw("");
    m.reset();
    onClose();
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    m.mutate(pw, {
      onSuccess: () => {
        toast.push("success", "Пароль сброшен, сессии сотрудника завершены");
        close();
      },
    });
  }
  return (
    <Dialog open={open} title="Сброс пароля" onClose={close}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <PasswordInput label="Новый пароль" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} error={fe} />
        <p className="text-xs text-muted">Не короче 10 символов. Сообщите пароль сотруднику лично.</p>
        {err && !fe && err.code !== "validation_error" && <Alert>{err.message}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={close}>Отмена</Button>
          <Button type="submit" loading={m.isPending} disabled={!pw}>Сбросить</Button>
        </div>
      </form>
    </Dialog>
  );
}
