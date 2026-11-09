import { type FormEvent, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthProvider";
import { Splash } from "@/features/auth/guards";
import { toAppError } from "@/shared/api/errors";
import { Alert, Button, Input, PasswordInput } from "@/shared/ui/ui";

/** C-01 «Вход» */
export function LoginPage() {
  const { user, status, expired, login } = useAuth();
  const loc = useLocation();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "loading") return <Splash />;
  if (user) {
    const from = (loc.state as { from?: string } | null)?.from;
    return <Navigate to={from && from.startsWith("/") && from !== "/login" ? from : "/"} replace />;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await login(name.trim(), password);
    } catch (err) {
      setError(toAppError(err).message);
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-full place-items-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-surface p-6" noValidate>
        <h1 className="text-xl font-semibold">CRM Автосервис</h1>
        {expired && !error && (
          <p role="status" className="text-sm text-muted">
            Сессия истекла, войдите снова
          </p>
        )}
        <Input label="Логин" autoComplete="username" autoFocus required value={name} onChange={(e) => setName(e.target.value)} className="min-h-11" />
        <PasswordInput label="Пароль" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="min-h-11" />
        {error && <Alert>{error}</Alert>}
        <Button type="submit" loading={busy} disabled={!name || !password} className="min-h-11 w-full">
          Войти
        </Button>
        <p className="text-xs text-muted">Забыли пароль? Обратитесь к руководителю — он задаст новый.</p>
      </form>
    </main>
  );
}
