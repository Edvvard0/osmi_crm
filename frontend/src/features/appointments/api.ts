import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import { toAppError } from "@/shared/api/errors";
import type { Appointment, AppointmentStatus, Department } from "@/shared/api/types";
import { toast } from "@/shared/ui/toast";

export interface AppointmentFilters {
  locationId: string;
  dateFrom: string;
  dateTo: string;
  department?: Department | "";
  postId?: string;
}

/** Записи точки за диапазон дат (даты — в поясе точки). */
export function useAppointments(f: AppointmentFilters) {
  const p = new URLSearchParams({ location_id: f.locationId, date_from: f.dateFrom, date_to: f.dateTo });
  if (f.department) p.set("department", f.department);
  if (f.postId) p.set("post_id", f.postId);
  return useQuery({
    queryKey: ["appointments", p.toString()],
    queryFn: () => api<Appointment[]>(`/appointments?${p.toString()}`),
    enabled: !!f.locationId && !!f.dateFrom && !!f.dateTo,
  });
}

export interface AppointmentCreate {
  location_id: string;
  client_id: string;
  vehicle_id: string;
  post_id?: string | null;
  department: Department;
  start_at: string;
  end_at: string;
  service_ids?: string[];
  comment?: string | null;
}

export interface AppointmentPatch {
  post_id?: string | null;
  start_at?: string;
  end_at?: string;
  department?: Department;
  service_ids?: string[];
  comment?: string | null;
}

export function useCreateAppointment() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: AppointmentCreate) => api<Appointment>("/appointments", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["appointments"] }),
  });
}

/** Правка из формы: ошибки показывает сама форма. */
export function useUpdateAppointment(id: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: AppointmentPatch) => api<Appointment>(`/appointments/${encodeURIComponent(id)}`, { method: "PATCH", body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["appointments"] }),
  });
}

/**
 * Перенос / изменение длительности перетаскиванием. Ошибка (в том числе 409 post_busy) → сообщение из словаря;
 * откат карточки делает страница, снимая временное положение.
 */
export function useMoveAppointment() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; patch: AppointmentPatch }) =>
      api<Appointment>(`/appointments/${encodeURIComponent(v.id)}`, { method: "PATCH", body: v.patch }),
    onSuccess: (data) => {
      // Сразу подставляем ответ сервера, чтобы карточка не мигала до обновления списка.
      qc.setQueriesData<Appointment[]>({ queryKey: ["appointments"] }, (old) => old?.map((a) => (a.id === data.id ? data : a)));
      return qc.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (e) => toast.error(toAppError(e)),
  });
}

export function useChangeStatus() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; status: AppointmentStatus }) =>
      api<Appointment>(`/appointments/${encodeURIComponent(v.id)}/status`, { body: { status: v.status } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["appointments"] }),
    onError: (e) => toast.error(toAppError(e)),
  });
}

/** Допустимые переходы статуса (зеркало контракта). */
export const NEXT_STATUSES: Record<AppointmentStatus, AppointmentStatus[]> = {
  scheduled: ["confirmed", "arrived", "no_show", "cancelled"],
  confirmed: ["arrived", "no_show", "cancelled"],
  arrived: [],
  no_show: [],
  cancelled: [],
};

/** Записи в конечных статусах нельзя править, перетаскивать и растягивать. */
export function isEditable(s: AppointmentStatus): boolean {
  return s === "scheduled" || s === "confirmed";
}
