import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import { fieldMessage, messageFor, toAppError } from "@/shared/api/errors";
import type { Page } from "@/shared/api/types";

import type {
  FinishResult,
  MechanicComment,
  MechanicPartRequest,
  MechanicTaskDetail,
  PartHit,
  PartRequestFull,
  PartRequestStatus,
  Priority,
  RecommendationStatus,
  TaskList,
  TaskScope,
  TimerResult,
  VehicleRecommendation,
} from "./types";

const enc = encodeURIComponent;
function qs(o: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/* ---------- Задачи механика ---------- */

export function useTasks(scope: TaskScope) {
  return useQuery({
    queryKey: ["mechanic", "tasks", scope],
    queryFn: () => api<TaskList>(`/mechanic/tasks?scope=${scope}`),
    refetchInterval: 60_000,
  });
}

export function useTask(id: string | undefined) {
  return useQuery({
    queryKey: ["mechanic", "task", id],
    queryFn: () => api<MechanicTaskDetail>(`/mechanic/tasks/${enc(id ?? "")}`),
    enabled: !!id,
  });
}

/** После таймера: свежая карточка кладётся в кэш, списки перечитываются. */
function useAfterTimer() {
  const qc = useQueryClient();
  return (r: TimerResult) => {
    qc.setQueryData<MechanicTaskDetail>(["mechanic", "task", r.task.item_id], (old) => (old ? { ...old, ...r.task, server_time: r.server_time } : old));
    void qc.invalidateQueries({ queryKey: ["mechanic"] });
  };
}

export function useStartTask() {
  const after = useAfterTimer();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { itemId: string; pauseActive?: boolean }) =>
      api<TimerResult>(`/mechanic/tasks/${enc(v.itemId)}/start`, { body: v.pauseActive ? { pause_active: true } : {} }),
    onSuccess: after,
  });
}

export function usePauseTask() {
  const after = useAfterTimer();
  return useMutation({
    meta: { silent: true },
    mutationFn: (itemId: string) => api<TimerResult>(`/mechanic/tasks/${enc(itemId)}/pause`, { body: {} }),
    onSuccess: after,
  });
}

export function useFinishTask() {
  const after = useAfterTimer();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { itemId: string; comment?: string }) =>
      api<FinishResult>(`/mechanic/tasks/${enc(v.itemId)}/finish`, { body: v.comment ? { comment: v.comment } : {} }),
    onSuccess: after,
  });
}

export function useAddTaskComment(itemId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (text: string) => api<MechanicComment>(`/mechanic/tasks/${enc(itemId)}/comments`, { body: { text } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mechanic", "task", itemId] }),
  });
}

/* ---------- Заявки на запчасти (механик) ---------- */

export function useMyPartRequests(status: "" | PartRequestStatus, limit: number) {
  return useQuery({
    queryKey: ["mechanic", "requests", status, limit],
    queryFn: () => api<Page<MechanicPartRequest>>(`/mechanic/part-requests${qs({ status, limit, offset: 0 })}`),
    placeholderData: keepPreviousData,
  });
}

export function useMechanicParts(search: string) {
  const s = search.trim();
  return useQuery({
    queryKey: ["mechanic", "parts", s],
    queryFn: () => api<PartHit[]>(`/mechanic/parts${qs({ search: s, limit: 20 })}`),
    enabled: s.length >= 2,
  });
}

export interface PartRequestInput { item_id: string; part_id?: string; description?: string; quantity?: string }
export function useCreatePartRequest() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: PartRequestInput) => api<MechanicPartRequest>("/mechanic/part-requests", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["mechanic", "requests"] }),
  });
}

export function useCreateMechanicRecommendation() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: { item_id: string; text: string; priority: Priority }) => api<VehicleRecommendation>("/mechanic/recommendations", { body: b }),
  });
}

/* ---------- Заявки на запчасти (менеджер, директор) ---------- */

export interface PartRequestFilters { locationId?: string; status?: "" | PartRequestStatus; orderId?: string; limit: number }

export function usePartRequests(f: PartRequestFilters) {
  const q = qs({ location_id: f.locationId, status: f.status, order_id: f.orderId, limit: f.limit, offset: 0 });
  return useQuery({
    queryKey: ["part-requests", "list", q],
    queryFn: () => api<Page<PartRequestFull>>(`/part-requests${q}`),
    placeholderData: keepPreviousData,
  });
}

export function usePartRequestSummary(locationId?: string) {
  const q = qs({ location_id: locationId });
  return useQuery({
    queryKey: ["part-requests", "summary", q],
    queryFn: () => api<{ new: number; approved: number }>(`/part-requests/summary${q}`),
  });
}

export function usePartRequestAction() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; action: "approve" | "reject" | "issue"; body: Record<string, unknown> }) =>
      api<unknown>(`/part-requests/${enc(v.id)}/${v.action}`, { body: v.body }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["part-requests"] });
      void qc.invalidateQueries({ queryKey: ["order"] });
      void qc.invalidateQueries({ queryKey: ["orders"] });
    },
  });
}

/** Возврат выполненной работы в исполнение (кнопка «Вернуть в работу» на карточке заказа). Ответ — полный WorkOrder. */
export function useReopenItem(orderId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { itemId: string; version: number }) =>
      api<{ id: string }>(`/work-orders/${enc(orderId)}/items/${enc(v.itemId)}/reopen`, { body: { version: v.version } }),
    onSuccess: (o) => {
      qc.setQueryData(["order", orderId], o);
      void qc.invalidateQueries({ queryKey: ["orders"] });
      void qc.invalidateQueries({ queryKey: ["order-history", orderId] });
    },
  });
}

/* ---------- Рекомендации по авто ---------- */

export function useVehicleRecommendations(vehicleId: string, status?: RecommendationStatus) {
  return useQuery({
    queryKey: ["recommendations", vehicleId, status ?? "all"],
    queryFn: () => api<VehicleRecommendation[]>(`/vehicles/${enc(vehicleId)}/recommendations${qs({ status })}`),
  });
}

export function useCreateRecommendation(vehicleId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: { text: string; priority: Priority; work_order_id?: string }) =>
      api<VehicleRecommendation>(`/vehicles/${enc(vehicleId)}/recommendations`, { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recommendations", vehicleId] }),
  });
}

export function usePatchRecommendation(vehicleId: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; body: { status?: RecommendationStatus; priority?: Priority; text?: string; work_order_id?: string } }) =>
      api<VehicleRecommendation>(`/recommendations/${enc(v.id)}`, { method: "PATCH", body: v.body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recommendations", vehicleId] }),
  });
}

/* ---------- Тексты ошибок ---------- */

/** Текст ошибки действий над заявками/рекомендациями (общие тексты invalid_transition/invalid_state относятся к записям). */
export function mechanicErrorText(e: unknown): string {
  const err = toAppError(e);
  switch (err.code) {
    case "invalid_transition":
      return "Заявка уже обработана. Обновите список";
    case "invalid_state":
      return "Действие недоступно в текущем статусе";
    case "version_conflict":
      return "Данные изменил другой сотрудник. Обновите список";
    case "insufficient_stock":
      return "На складе недостаточно остатка";
    case "forbidden":
      return "Недостаточно прав для этого действия";
    case "validation_error": {
      const texts = Object.keys(err.fields).map((n) => fieldMessage(err, n)).filter(Boolean);
      return texts.length ? texts.join(". ") : messageFor("validation_error");
    }
    default:
      return err.message;
  }
}
