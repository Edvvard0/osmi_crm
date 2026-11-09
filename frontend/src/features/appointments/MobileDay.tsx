import clsx from "clsx";

import { APPOINTMENT_STATUS_LABELS, type Appointment, type Post } from "@/shared/api/types";

import { StatusMark, statusBoxClass, struckClass, vehicleTitle } from "./status";
import { hhmm, minuteOfDay } from "./time";

interface Props {
  tz: string;
  appointments: Appointment[];
  posts: Post[];
  /** "" — все посты; "none" — записи без поста; иначе id поста. */
  post: string;
  onPost: (p: string) => void;
  onOpen: (a: Appointment) => void;
}

/** Список записей выбранного дня для телефона; посты переключаются чипами. */
export function MobileDay({ tz, appointments, posts, post, onPost, onOpen }: Props) {
  const hasNone = appointments.some((a) => a.post_id === null);
  const chips: { key: string; label: string }[] = [
    { key: "", label: "Все посты" },
    ...posts.map((p) => ({ key: p.id, label: p.name })),
    ...(hasNone ? [{ key: "none", label: "Без поста" }] : []),
  ];
  const postName = (id: string | null) => (id ? (posts.find((p) => p.id === id)?.name ?? "") : "Без поста");
  const shown = appointments
    .filter((a) => (post === "" ? true : post === "none" ? a.post_id === null : a.post_id === post))
    .sort((a, b) => Date.parse(a.start_at) - Date.parse(b.start_at));

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Посты" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
        {chips.map((c) => (
          <button
            key={c.key}
            type="button"
            aria-pressed={post === c.key}
            onClick={() => onPost(c.key)}
            className={clsx(
              "min-h-10 shrink-0 rounded-full border px-4 text-sm",
              post === c.key ? "border-accent bg-accent text-accent-fg" : "border-border bg-surface text-fg",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">На этот день записей нет</p>
      ) : (
        <ul className="space-y-2" aria-label="Записи дня">
          {shown.map((a) => {
            const time = `${hhmm(minuteOfDay(Date.parse(a.start_at), tz))}–${hhmm(minuteOfDay(Date.parse(a.end_at), tz))}`;
            return (
              <li key={a.id}>
                <button
                  type="button"
                  data-appointment={a.id}
                  aria-label={`${time}, ${vehicleTitle(a)}, ${a.client.full_name}, ${APPOINTMENT_STATUS_LABELS[a.status]}`}
                  onClick={() => onOpen(a)}
                  className={clsx("block min-h-14 w-full rounded border border-border px-3 py-2 text-left text-sm", statusBoxClass(a.status))}
                >
                  <span className={clsx("flex items-center justify-between gap-2", struckClass(a.status))}>
                    <span className="font-medium tabular-nums">{time}</span>
                    <span className="flex items-center gap-1 text-xs text-muted">
                      <StatusMark status={a.status} />
                      {post === "" && <span>{postName(a.post_id)}</span>}
                    </span>
                  </span>
                  <span className={clsx("block truncate font-medium", struckClass(a.status))}>{vehicleTitle(a)}</span>
                  <span className={clsx("block truncate text-muted", struckClass(a.status))}>{a.client.full_name}</span>
                  {a.services.length > 0 && (
                    <span className={clsx("block truncate text-muted", struckClass(a.status))}>{a.services.map((s) => s.name).join(", ")}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
