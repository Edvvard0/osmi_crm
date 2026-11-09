import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { useMe } from "@/features/auth/AuthProvider";
import { SessionsSection } from "@/features/audit/SessionsSection";
import { useLocations } from "@/features/locations/api";
import { TelegramSection } from "@/features/telegram/TelegramSection";
import { api } from "@/shared/api/client";
import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import { ROLE_LABELS } from "@/shared/api/types";
import { type Theme, getTheme, setTheme } from "@/shared/lib/theme";
import { useToast } from "@/shared/ui/toast";
import { Alert, Button, PasswordInput, Select } from "@/shared/ui/ui";

const MIN_LEN = 10;

/** C-02 «Настройки» */
export function SettingsPage() {
  return (
    <div className="mx-auto max-w-xl space-y-8">
      <h1 className="text-xl font-semibold">Настройки</h1>
      <ProfileSection />
      <PasswordSection />
      <SessionsSection />
      <TelegramSection />
      <AppearanceSection />
    </div>
  );
}

function ProfileSection() {
  const me = useMe();
  const locs = useLocations();
  const names = (locs.data ?? []).filter((l) => me.location_ids.includes(l.id)).map((l) => l.name);
  return (
    <section aria-labelledby="s-profile" className="space-y-2">
      <h2 id="s-profile" className="text-base font-semibold">Профиль</h2>
      <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
        <dt className="text-muted">ФИО</dt>
        <dd>{me.full_name}</dd>
        <dt className="text-muted">Логин</dt>
        <dd>{me.login}</dd>
        <dt className="text-muted">Роль</dt>
        <dd>{ROLE_LABELS[me.role]}</dd>
        <dt className="text-muted">Точки</dt>
        <dd>{names.length ? names.join(", ") : "—"}</dd>
      </dl>
    </section>
  );
}

function PasswordSection() {
  const me = useMe();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);
  const m = useMutation({
    meta: { silent: true },
    mutationFn: () => api<void>("/auth/change-password", { body: { current_password: current, new_password: next } }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setRepeat("");
      toast.push("success", "Пароль изменён");
    },
  });
  const err: AppError | null = m.error ? toAppError(m.error) : null;

  const longEnough = next.length >= MIN_LEN;
  const notLogin = next.length > 0 && next.toLowerCase() !== me.login.toLowerCase();

  function submit(e: FormEvent) {
    e.preventDefault();
    setLocalErr(null);
    if (next !== repeat) {
      setLocalErr("Пароли не совпадают");
      return;
    }
    m.mutate();
  }

  const currentErr = err?.code === "invalid_current_password" ? err.message : fieldMessage(err, "current_password");
  const newErr = fieldMessage(err, "new_password");
  const generalErr = err && !currentErr && !newErr && err.code !== "validation_error" ? err.message : null;

  return (
    <section aria-labelledby="s-pass" className="space-y-3">
      <h2 id="s-pass" className="text-base font-semibold">Безопасность</h2>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <PasswordInput label="Текущий пароль" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} error={currentErr} />
        <PasswordInput label="Новый пароль" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} error={newErr} />
        <ul className="space-y-0.5 text-xs text-muted" aria-label="Требования к паролю">
          <li className={longEnough ? "text-success" : undefined}>
            {longEnough ? "✓" : "○"} Не короче {MIN_LEN} символов
          </li>
          <li className={notLogin ? "text-success" : undefined}>{notLogin ? "✓" : "○"} Не совпадает с логином</li>
        </ul>
        <PasswordInput label="Повторите новый пароль" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} error={localErr ?? undefined} />
        {generalErr && <Alert>{generalErr}</Alert>}
        <Button type="submit" loading={m.isPending} disabled={!current || !next || !repeat}>
          Сменить пароль
        </Button>
        <p className="text-xs text-muted">После смены пароля другие устройства выйдут из системы.</p>
      </form>
    </section>
  );
}

function AppearanceSection() {
  const [theme, setT] = useState<Theme>(getTheme);
  return (
    <section aria-labelledby="s-look" className="space-y-2">
      <h2 id="s-look" className="text-base font-semibold">Внешний вид</h2>
      <Select
        label="Тема"
        value={theme}
        onChange={(e) => {
          const t = e.target.value as Theme;
          setT(t);
          setTheme(t);
        }}
      >
        <option value="system">Системная</option>
        <option value="light">Светлая</option>
        <option value="dark">Тёмная</option>
      </Select>
    </section>
  );
}
