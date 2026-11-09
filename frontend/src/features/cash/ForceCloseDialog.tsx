import { useState } from "react";

import { formatMoney } from "@/shared/lib/money";
import { Modal } from "@/shared/ui/modal";
import { Alert, Button, Textarea } from "@/shared/ui/ui";

import { cashErrorText } from "./lib";

/**
 * «Закрыть без полной оплаты» (директор). `submit(comment)` выполняет смену статуса
 * `POST /work-orders/{id}/status {status:"closed", version, force_close:true, comment}` на стороне карточки заказа
 * и должен вернуть Promise (ошибка показывается в диалоге; при успехе диалог закрывается).
 */
export function ForceCloseDialog({ balanceDue, onClose, submit }: { balanceDue: string; onClose: () => void; submit: (comment: string) => Promise<unknown> }) {
  const [comment, setComment] = useState("");
  const [fieldErr, setFieldErr] = useState<string>();
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (pending) return;
    const text = comment.trim();
    if (!text) {
      setFieldErr("Укажите причину закрытия без оплаты");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await submit(text);
      onClose();
    } catch (x) {
      setError(x);
      setPending(false);
    }
  }

  return (
    <Modal title="Закрыть без полной оплаты" onClose={onClose}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <p className="text-sm">
          Остаток к оплате: <strong className="tabular-nums">{formatMoney(balanceDue)}</strong>. Заказ будет закрыт с отметкой «закрыт без полной оплаты».
        </p>
        <Textarea
          label="Комментарий"
          maxLength={500}
          value={comment}
          error={fieldErr}
          onChange={(e) => {
            setComment(e.target.value);
            setFieldErr(undefined);
          }}
        />
        {error !== null && <Alert>{cashErrorText(error)}</Alert>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="danger" loading={pending}>Закрыть заказ</Button>
        </div>
      </form>
    </Modal>
  );
}
