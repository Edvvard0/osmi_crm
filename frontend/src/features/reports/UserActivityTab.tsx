import clsx from "clsx";
import { useSearchParams } from "react-router-dom";

import { ActivityPanel } from "./ActivityPanel";

type Tab = "data" | "activity";

const TABS: { key: Tab; label: string }[] = [
  { key: "data", label: "Данные" },
  { key: "activity", label: "Активность" },
];

/** Вкладка выбирается параметром ?tab=activity; по умолчанию «Данные». */
export function useUserTab(): [Tab, (t: Tab) => void] {
  const [sp, setSp] = useSearchParams();
  const tab: Tab = sp.get("tab") === "activity" ? "activity" : "data";
  const set = (t: Tab) => {
    const next = new URLSearchParams(sp);
    if (t === "data") next.delete("tab");
    else next.set("tab", t);
    setSp(next, { replace: true });
  };
  return [tab, set];
}

export function UserTabs({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <div role="tablist" aria-label="Разделы карточки" className="mx-auto flex max-w-xl gap-1 border-b border-border">
      {TABS.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          aria-selected={tab === t.key}
          onClick={() => onChange(t.key)}
          className={clsx("min-h-10 border-b-2 px-4 text-sm", tab === t.key ? "border-accent font-medium" : "border-transparent text-muted hover:text-fg")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** D-05: карта рабочих дней выбранного сотрудника (механик — часы работ, менеджер/директор — действия). */
export function UserActivityTab({ userId, fullName }: { userId: string; fullName: string }) {
  return (
    <div role="tabpanel" aria-label="Активность" className="mx-auto max-w-4xl space-y-4">
      <h1 className="break-words text-xl font-semibold">{fullName}</h1>
      <ActivityPanel userId={userId} defaultRange="12m" />
    </div>
  );
}
