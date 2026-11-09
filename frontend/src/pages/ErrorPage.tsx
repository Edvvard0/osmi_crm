import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/shared/ui/ui";

function Centered({ title, text, children, extra }: { title: string; text: string; children?: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <section aria-labelledby="err-title" className="grid min-h-[60vh] place-items-center p-6 text-center">
      <div className="max-w-sm">
        <h1 id="err-title" className="text-xl font-semibold">{title}</h1>
        <p className="mt-2 text-sm text-muted">{text}</p>
        {extra}
        <div className="mt-5 flex flex-wrap justify-center gap-2">{children}</div>
      </div>
    </section>
  );
}

function CopyCode({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <p className="mt-3 flex items-center justify-center gap-2 text-sm text-muted">
      <span>Код обращения:</span>
      <code className="font-mono text-fg">{code}</code>
      <Button
        variant="ghost"
        offlineSafe
        className="px-2"
        onClick={() => {
          void navigator.clipboard?.writeText(code).then(() => setCopied(true), () => undefined);
        }}
      >
        {copied ? "Скопировано" : "Копировать"}
      </Button>
    </p>
  );
}

/**
 * C-06 «Что-то пошло не так». Без технических деталей: только код обращения, по которому ошибку найдут в логе.
 * «Обновить страницу» перезагружает приложение (подходит и для ошибки загрузки чанка после выхода новой версии).
 */
export function ErrorPage({ code }: { code?: string; onRetry?: () => void }) {
  return (
    <Centered
      title="Что-то пошло не так"
      text="Мы уже знаем о проблеме. Попробуйте обновить страницу. Если не поможет — сообщите код руководителю."
      extra={code ? <CopyCode code={code} /> : null}
    >
      <Button offlineSafe onClick={() => location.reload()}>Обновить страницу</Button>
      <Button variant="secondary" offlineSafe onClick={() => location.assign("/")}>На главную</Button>
    </Centered>
  );
}

/** C-03 «Не найдено» */
export function NotFoundPage() {
  return (
    <Centered title="Не найдено" text="Такой страницы нет или она была удалена.">
      <Button offlineSafe onClick={() => location.assign("/")}>На главную</Button>
    </Centered>
  );
}

/** C-03 «Нет доступа» */
export function ForbiddenPage() {
  return (
    <Centered title="Нет доступа" text="У вашей роли нет прав на этот раздел.">
      <Link to="/" className="inline-flex min-h-11 items-center rounded bg-accent px-4 md:min-h-10 text-sm font-medium text-accent-fg">
        На главную
      </Link>
    </Centered>
  );
}
