import { Link } from "react-router-dom";

import { Button } from "@/shared/ui/ui";

function Centered({ title, text, children }: { title: string; text: string; children?: React.ReactNode }) {
  return (
    <main className="grid min-h-[60vh] place-items-center p-6 text-center">
      <div className="max-w-sm">
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-2 text-sm text-muted">{text}</p>
        <div className="mt-5 flex justify-center gap-2">{children}</div>
      </div>
    </main>
  );
}

/** C-06 «Что-то пошло не так» */
export function ErrorPage({ onRetry }: { onRetry?: () => void }) {
  return (
    <Centered title="Что-то пошло не так" text="Мы уже знаем о проблеме. Попробуйте обновить страницу.">
      <Button onClick={() => (onRetry ? onRetry() : location.reload())}>Повторить</Button>
      <Button variant="secondary" onClick={() => location.assign("/")}>На главную</Button>
    </Centered>
  );
}

/** C-03 «Не найдено» */
export function NotFoundPage() {
  return (
    <Centered title="Не найдено" text="Такой страницы нет или она была удалена.">
      <Button onClick={() => location.assign("/")}>На главную</Button>
    </Centered>
  );
}

/** C-03 «Нет доступа» */
export function ForbiddenPage() {
  return (
    <Centered title="Нет доступа" text="У вашей роли нет прав на этот раздел.">
      <Link to="/" className="inline-flex min-h-10 items-center rounded bg-accent px-4 text-sm font-medium text-accent-fg">
        На главную
      </Link>
    </Centered>
  );
}
