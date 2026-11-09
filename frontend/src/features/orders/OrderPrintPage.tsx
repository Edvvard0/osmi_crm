import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { NotFoundPage } from "@/pages/ErrorPage";
import { api } from "@/shared/api/client";
import { toAppError } from "@/shared/api/errors";
import { Button } from "@/shared/ui/ui";

import { useOrder } from "./api";
import { LoadError, Skeleton } from "./ui";

type Form = "order" | "act";
const FORM_LABELS: Record<Form, string> = { order: "Заказ-наряд", act: "Акт выполненных работ" };

/** MG-07: предпросмотр PDF. Файл скачивается через api() как Blob (нужен Authorization) и показывается по blob:-URL. */
export function OrderPrintPage() {
  const { id = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const order = useOrder(id);
  const actAvailable = order.data ? order.data.status === "ready" || order.data.status === "closed" : false;
  const requested: Form = sp.get("form") === "act" ? "act" : "order";
  const form: Form = requested === "act" && actAvailable ? "act" : "order";

  const pdf = useQuery({
    queryKey: ["order-pdf", id, form],
    queryFn: () => api<Blob>(`/work-orders/${encodeURIComponent(id)}/print/${form === "act" ? "act" : "work-order"}`, { blob: true }),
    enabled: !!order.data,
    staleTime: 0,
    gcTime: 0,
  });

  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!pdf.data || typeof URL.createObjectURL !== "function") {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(pdf.data);
    setUrl(u);
    return () => {
      if (typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(u);
    };
  }, [pdf.data]);

  const frame = useRef<HTMLIFrameElement>(null);

  if (order.isLoading) return <Skeleton lines={4} />;
  if (order.error) return toAppError(order.error).status === 404 ? <NotFoundPage /> : <LoadError error={order.error} onRetry={() => void order.refetch()} />;
  if (!order.data) return null;
  const number = order.data.number;

  function print() {
    try {
      frame.current?.contentWindow?.focus();
      frame.current?.contentWindow?.print();
    } catch {
      if (url) window.open(url, "_blank", "noopener");
    }
  }

  return (
    <div className="space-y-3">
      <Link to={`/orders/${encodeURIComponent(id)}`} className="text-sm text-muted underline">← Заказ {number}</Link>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Печать: {number}</h1>
        <div className="flex flex-wrap gap-2">
          <div role="group" aria-label="Форма документа" className="inline-flex overflow-hidden rounded border border-border">
            {(Object.keys(FORM_LABELS) as Form[]).map((f) => {
              const off = f === "act" && !actAvailable;
              return (
                <button
                  key={f}
                  type="button"
                  disabled={off}
                  aria-pressed={form === f}
                  title={off ? "Акт доступен после статуса «Готов»" : undefined}
                  onClick={() => setSp(f === "act" ? { form: "act" } : {}, { replace: true })}
                  className={clsx("min-h-10 px-3 text-sm disabled:cursor-not-allowed disabled:text-muted", form === f ? "bg-accent text-accent-fg" : "bg-surface hover:bg-bg")}
                >
                  {FORM_LABELS[f]}
                </button>
              );
            })}
          </div>
          <Button type="button" disabled={!url} onClick={print}>Печать</Button>
          {url ? (
            <a className="inline-flex min-h-10 items-center rounded border border-border bg-surface px-4 text-sm font-medium hover:bg-bg" href={url} download={`${number}-${form}.pdf`}>
              Скачать
            </a>
          ) : (
            <Button type="button" variant="secondary" disabled>Скачать</Button>
          )}
        </div>
      </div>
      {!actAvailable && <p className="text-xs text-muted">Акт выполненных работ доступен после перевода заказа в статус «Готов».</p>}

      {pdf.isLoading ? (
        <Skeleton lines={6} />
      ) : pdf.error ? (
        <LoadError error={pdf.error} onRetry={() => void pdf.refetch()} />
      ) : url ? (
        <iframe ref={frame} title="Предпросмотр PDF" src={url} className="h-[75vh] w-full rounded-lg border border-border bg-surface" />
      ) : (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted">Предпросмотр недоступен в этом браузере. Используйте «Скачать».</p>
      )}
    </div>
  );
}
