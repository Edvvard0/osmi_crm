import { useState } from "react";

import { type AppError, fieldMessage, toAppError } from "@/shared/api/errors";
import type { CrmLocation } from "@/shared/api/types";
import { useToast } from "@/shared/ui/toast";
import { Alert, Badge, Button, Input } from "@/shared/ui/ui";

import { useLocationTelegramTest, useSetLocationChat } from "./api";

const INT64 = /^-?\d{1,19}$/;
const MAX = 9223372036854775807n;

/** D-06: поле «Telegram-чат точки». Директор редактирует, остальные видят только статус. */
export function LocationTelegram({ loc, isDirector }: { loc: CrmLocation; isDirector: boolean }) {
  const toast = useToast();
  const save = useSetLocationChat(loc.id);
  const test = useLocationTelegramTest(loc.id);
  const [value, setValue] = useState(loc.telegram_chat_id != null ? String(loc.telegram_chat_id) : "");
  const [localErr, setLocalErr] = useState<string>();
  const [result, setResult] = useState<"ok" | AppError | null>(null);

  const connected = loc.has_telegram_chat ?? false;
  const badge = <Badge tone={connected ? "success" : "neutral"}>{connected ? "Чат подключён" : "Чат не подключён"}</Badge>;

  if (!isDirector) {
    return (
      <section aria-labelledby="s-loc-tg" className="space-y-2 border-t border-border pt-4">
        <h2 id="s-loc-tg" className="text-base font-semibold">Telegram-чат точки</h2>
        {badge}
      </section>
    );
  }

  const saveErr = save.error ? toAppError(save.error) : null;
  const fieldErr = localErr ?? fieldMessage(saveErr, "telegram_chat_id");

  function submit() {
    setLocalErr(undefined);
    setResult(null);
    const v = value.trim();
    if (v === "") {
      save.mutate(null, { onSuccess: () => toast.push("success", "Чат отключён") });
      return;
    }
    if (!INT64.test(v) || BigInt(v) > MAX || BigInt(v) < -MAX - 1n) {
      setLocalErr("ID чата — целое число, например -1001234567890");
      return;
    }
    save.mutate(Number(v), { onSuccess: () => toast.push("success", "Чат сохранён") });
  }

  function runTest() {
    setResult(null);
    test.mutate(undefined, {
      onSuccess: () => setResult("ok"),
      onError: (e) => setResult(toAppError(e)),
    });
  }

  const testErr = result && result !== "ok" ? (fieldMessage(result, "telegram_chat_id") ?? result.message) : null;

  return (
    <section aria-labelledby="s-loc-tg" className="space-y-3 border-t border-border pt-4">
      <div className="flex items-center justify-between gap-2">
        <h2 id="s-loc-tg" className="text-base font-semibold">Telegram-чат точки</h2>
        {badge}
      </div>
      <Input
        label="ID чата"
        id="loc-tg-chat"
        inputMode="numeric"
        placeholder="-1001234567890"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        error={fieldErr}
      />
      <p className="text-xs text-muted">Добавьте бота в группу и отправьте /chatid. Пустое значение отключает чат.</p>
      {saveErr && !fieldErr && saveErr.code !== "validation_error" && <Alert>{saveErr.message}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={submit} loading={save.isPending}>Сохранить чат</Button>
        <Button variant="secondary" onClick={runTest} loading={test.isPending} disabled={!connected}>Отправить тест</Button>
      </div>
      {result === "ok" && <p role="status" className="text-sm text-success">Тестовое сообщение отправлено</p>}
      {testErr && <Alert>{testErr}</Alert>}
    </section>
  );
}
