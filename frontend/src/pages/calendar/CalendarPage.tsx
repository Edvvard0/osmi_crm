import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AppointmentDetails } from "@/features/appointments/AppointmentDetails";
import { AppointmentForm, type FormInitial } from "@/features/appointments/AppointmentForm";
import { CalendarGrid, type CalendarColumn, type MovePayload } from "@/features/appointments/CalendarGrid";
import { MobileDay } from "@/features/appointments/MobileDay";
import { useAppointments, useMoveAppointment } from "@/features/appointments/api";
import { gridRange, snap, validateInterval } from "@/features/appointments/grid";
import {
  addDays,
  dateOfMs,
  formatDay,
  formatDayShort,
  isDateStr,
  minuteOfDay,
  parseHm,
  safeZone,
  todayIn,
  toZonedIso,
  weekDates,
  zonedTimeToMs,
} from "@/features/appointments/time";
import { usePosts } from "@/features/catalog/api";
import { useActiveLocation } from "@/features/locations/api";
import { AppError, toAppError } from "@/shared/api/errors";
import { type Appointment, DEPARTMENT_LABELS, type Department } from "@/shared/api/types";
import { useMediaQuery } from "@/shared/lib/useMediaQuery";
import { toast } from "@/shared/ui/toast";
import { Alert, Button, Input, Loading, Select } from "@/shared/ui/ui";

type Mode = "day" | "week";
type DeptFilter = "" | Department;

/** Временное положение карточки, пока перенос не подтверждён сервером. */
interface Override {
  postId: string | null;
  startMs: number;
  endMs: number;
}

type FormState = { kind: "create"; initial: FormInitial } | { kind: "edit"; id: string } | null;

const NONE = "none";

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex overflow-hidden rounded border border-border">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "min-h-10 border-r border-border px-3 text-sm last:border-r-0",
            value === o.value ? "bg-accent text-accent-fg" : "bg-surface text-fg hover:bg-border/40",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function CalendarPage() {
  const { items: locations, value: activeId, set: setLocation, loading: locLoading } = useActiveLocation();
  const location = locations.find((l) => l.id === activeId) ?? locations[0] ?? null;
  const locationId = location?.id ?? "";
  const tz = safeZone(location?.timezone ?? "UTC");
  const isMobile = useMediaQuery("(max-width: 767px)");

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  const [mode, setMode] = useState<Mode>("day");
  const [dateState, setDate] = useState<string | null>(null);
  const [dept, setDept] = useState<DeptFilter>("");
  const [weekPost, setWeekPost] = useState("");
  const [mobilePost, setMobilePost] = useState("");
  const [form, setForm] = useState<FormState>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Override>>({});

  const today = todayIn(tz, now);
  const date = dateState && isDateStr(dateState) ? dateState : today;
  const effMode: Mode = isMobile ? "day" : mode;
  const dates = useMemo(() => (effMode === "week" ? weekDates(date) : [date]), [effMode, date]);
  const dateFrom = dates[0];
  const dateTo = dates[dates.length - 1];

  const postsQ = usePosts(locationId);
  const posts = useMemo(
    () =>
      (postsQ.data ?? [])
        .filter((p) => p.is_active && (!dept || p.department === dept))
        .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, "ru")),
    [postsQ.data, dept],
  );
  const allActivePosts = useMemo(() => (postsQ.data ?? []).filter((p) => p.is_active), [postsQ.data]);

  const apptQ = useAppointments({ locationId, dateFrom, dateTo, department: dept });
  const move = useMoveAppointment();

  const work = useMemo(
    () => ({ start: parseHm(location?.work_start ?? "09:00") ?? 9 * 60, end: parseHm(location?.work_end ?? "21:00") ?? 21 * 60 }),
    [location?.work_start, location?.work_end],
  );

  // Записи с учётом незавершённых переносов.
  const appointments = useMemo<Appointment[]>(
    () =>
      (apptQ.data ?? []).map((a) => {
        const o = overrides[a.id];
        return o ? { ...a, post_id: o.postId, start_at: toZonedIso(o.startMs, tz), end_at: toZonedIso(o.endMs, tz) } : a;
      }),
    [apptQ.data, overrides, tz],
  );

  const selectedWeekPost = posts.some((p) => p.id === weekPost) ? weekPost : (posts[0]?.id ?? "");

  const visible = useMemo(
    () => (effMode === "week" ? appointments.filter((a) => a.post_id === selectedWeekPost) : appointments),
    [appointments, effMode, selectedWeekPost],
  );

  const columns = useMemo<CalendarColumn[]>(() => {
    if (effMode === "week") {
      const post = posts.find((p) => p.id === selectedWeekPost);
      return dates.map((d) => ({
        key: d,
        label: formatDayShort(d),
        sub: post?.name,
        date: d,
        postId: post?.id ?? null,
        department: post?.department,
      }));
    }
    const cols: CalendarColumn[] = posts.map((p) => ({
      key: p.id,
      label: p.name,
      sub: DEPARTMENT_LABELS[p.department],
      date,
      postId: p.id,
      department: p.department,
    }));
    if (appointments.some((a) => a.post_id === null)) cols.push({ key: NONE, label: "Без поста", date, postId: null });
    return cols;
  }, [effMode, posts, selectedWeekPost, date, dates, appointments]);

  const colKeyOf = (a: Appointment) => (effMode === "week" ? dateOfMs(Date.parse(a.start_at), tz) : (a.post_id ?? NONE));

  const range = useMemo(
    () =>
      gridRange(
        work,
        visible.map((a) => ({ start: minuteOfDay(Date.parse(a.start_at), tz), end: minuteOfDay(Date.parse(a.end_at), tz) || 24 * 60 })),
      ),
    [work, visible, tz],
  );

  function defaultStart(forDate: string): number {
    const base = forDate === today ? Math.max(work.start, snap(minuteOfDay(now, tz), 15, "ceil")) : work.start;
    return Math.min(base, Math.max(work.start, work.end - 60));
  }

  function newFromButton() {
    const post = effMode === "week" ? selectedWeekPost : isMobile ? mobilePost : "";
    const postId = post && post !== NONE ? post : (posts[0]?.id ?? null);
    setForm({ kind: "create", initial: { postId, date, startMin: defaultStart(date), department: dept || undefined } });
  }

  function handleMove(p: MovePayload) {
    const a = p.appointment;
    if (validateInterval(p.interval, work)) {
      toast.error(new AppError("outside_working_hours", 422));
      return;
    }
    const startMs = zonedTimeToMs(p.column.date, p.interval.start, tz);
    const endMs = zonedTimeToMs(p.column.date, p.interval.end, tz);
    setOverrides((o) => ({ ...o, [a.id]: { postId: p.column.postId, startMs, endMs } }));
    const clear = () =>
      setOverrides((o) => Object.fromEntries(Object.entries(o).filter(([id]) => id !== a.id)));
    move.mutate(
      { id: a.id, patch: { post_id: p.column.postId, start_at: toZonedIso(startMs, tz), end_at: toZonedIso(endMs, tz) } },
      { onSettled: clear },
    );
  }

  function shift(dir: -1 | 1) {
    setDate(addDays(date, dir * (effMode === "week" ? 7 : 1)));
  }

  const openAppt = appointments.find((a) => a.id === openId) ?? null;
  const editAppt = form?.kind === "edit" ? (appointments.find((a) => a.id === form.id) ?? null) : null;
  const title = effMode === "week" ? `${formatDay(dateFrom)} — ${formatDay(dateTo)}` : formatDay(date);

  if (locLoading) return <Loading />;
  if (!location) return <Alert>Нет доступных точек</Alert>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Календарь</h1>
        <Button type="button" onClick={newFromButton}>Новая запись</Button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {locations.length > 1 && (
          <div className="min-w-40">
            <Select id="cal-location" label="Точка календаря" value={locationId} onChange={(e) => setLocation(e.target.value)}>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </Select>
          </div>
        )}
        {!isMobile && (
          <Segmented<Mode>
            label="Режим"
            value={mode}
            onChange={setMode}
            options={[
              { value: "day", label: "День" },
              { value: "week", label: "Неделя" },
            ]}
          />
        )}
        <Segmented<DeptFilter>
          label="Отдел"
          value={dept}
          onChange={setDept}
          options={[
            { value: "", label: "Все" },
            { value: "service", label: "Сервис" },
            { value: "detailing", label: "Детейлинг" },
          ]}
        />
        {effMode === "week" && !isMobile && posts.length > 0 && (
          <div className="min-w-40">
            <Select id="cal-week-post" label="Пост недели" value={selectedWeekPost} onChange={(e) => setWeekPost(e.target.value)}>
              {posts.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="secondary" aria-label={effMode === "week" ? "Предыдущая неделя" : "Предыдущий день"} onClick={() => shift(-1)}><ChevronLeft size={18} aria-hidden="true" /></Button>
        <Button type="button" variant="secondary" onClick={() => setDate(today)}>Сегодня</Button>
        <Button type="button" variant="secondary" aria-label={effMode === "week" ? "Следующая неделя" : "Следующий день"} onClick={() => shift(1)}><ChevronRight size={18} aria-hidden="true" /></Button>
        <div className="w-40">
          <Input id="cal-date" label="Дата" type="date" value={date} onChange={(e) => isDateStr(e.target.value) && setDate(e.target.value)} />
        </div>
        <h2 className="min-w-0 flex-1 text-base font-medium" aria-live="polite">{title}</h2>
      </div>

      {(postsQ.isError || apptQ.isError) && <Alert>{toAppError(postsQ.error ?? apptQ.error).message}</Alert>}
      {(postsQ.isLoading || apptQ.isLoading) && <Loading />}

      {postsQ.isSuccess && apptQ.isSuccess && (
        isMobile ? (
          <MobileDay tz={tz} appointments={appointments} posts={posts} post={mobilePost} onPost={setMobilePost} onOpen={(a) => setOpenId(a.id)} />
        ) : columns.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">Для этой точки нет активных постов</p>
        ) : (
          <CalendarGrid
            tz={tz}
            columns={columns}
            appointments={visible}
            work={work}
            range={range}
            now={now}
            colKeyOf={colKeyOf}
            onCreate={(c, m) => setForm({ kind: "create", initial: { postId: c.postId, date: c.date, startMin: m, department: c.department } })}
            onOpen={(a) => setOpenId(a.id)}
            onMove={handleMove}
          />
        )
      )}

      {openAppt && !form && (
        <AppointmentDetails
          appointment={openAppt}
          tz={tz}
          postName={openAppt.post_id ? (allActivePosts.find((p) => p.id === openAppt.post_id)?.name ?? "Пост") : null}
          onClose={() => setOpenId(null)}
          onEdit={() => setForm({ kind: "edit", id: openAppt.id })}
        />
      )}
      {form?.kind === "create" && (
        <AppointmentForm location={location} posts={allActivePosts} initial={form.initial} onClose={() => setForm(null)} onSaved={() => setForm(null)} />
      )}
      {form?.kind === "edit" && editAppt && (
        <AppointmentForm
          location={location}
          posts={allActivePosts}
          appointment={editAppt}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null);
            setOpenId(null);
          }}
        />
      )}
    </div>
  );
}
