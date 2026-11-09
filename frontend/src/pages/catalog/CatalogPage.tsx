import clsx from "clsx";
import { useState } from "react";

import { useMe } from "@/features/auth/AuthProvider";
import { useActiveLocation } from "@/features/locations/api";

import { PartsTab } from "./PartsTab";
import { PostsTab } from "./PostsTab";
import { PricesTab } from "./PricesTab";
import { ServicesTab } from "./ServicesTab";

type TabId = "services" | "prices" | "posts" | "parts";

/** D-07 «Каталог и цены» (руководитель) и MG-15 «Каталог» (менеджер, только просмотр). */
export function CatalogPage() {
  const me = useMe();
  const canEdit = me.role === "director";
  const { value: activeLoc } = useActiveLocation();
  const tabs: { id: TabId; label: string }[] = [
    { id: "services", label: "Услуги" },
    ...(canEdit ? [{ id: "prices" as const, label: "Цены по точкам" }, { id: "posts" as const, label: "Посты" }] : []),
    { id: "parts", label: "Запчасти и материалы" },
  ];
  const [tab, setTab] = useState<TabId>("services");

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{canEdit ? "Каталог и цены" : "Каталог"}</h1>
      <div role="tablist" aria-label="Разделы каталога" className="flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="catalog-panel"
            onClick={() => setTab(t.id)}
            className={clsx(
              "min-h-10 shrink-0 whitespace-nowrap border-b-2 px-3 text-sm font-medium",
              tab === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="catalog-panel" aria-labelledby={`tab-${tab}`}>
        {tab === "services" && <ServicesTab canEdit={canEdit} locationId={canEdit ? undefined : activeLoc} />}
        {tab === "prices" && canEdit && <PricesTab />}
        {tab === "posts" && canEdit && <PostsTab />}
        {tab === "parts" && <PartsTab canEdit={canEdit} />}
      </div>
    </div>
  );
}
