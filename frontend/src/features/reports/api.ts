import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api/client";
import type { Department } from "@/shared/api/types";

import { enc, qs } from "./lib";
import type {
  ActivityDetails,
  ActivityHeatmapData,
  Dashboard,
  DashboardToday,
  LocationSummary,
  MyEarnings,
  PayrollAdjustment,
  PayrollDetail,
  PayrollScheme,
  PayrollSchemeType,
  PayrollSheet,
  Report,
  ReportId,
  SummaryPeriod,
} from "./types";

/** "all" (выбор директора) и пустое значение означают «все точки» — параметр не передаётся. */
export const locParam = (locationId: string): string => (locationId === "all" ? "" : locationId);

/* ---------- Дашборд (D-01), сводки (MG-16, MG-01) ---------- */

export function useDashboard(f: { locationId: string; dateFrom: string; dateTo: string }) {
  const q = qs({ location_id: locParam(f.locationId), date_from: f.dateFrom, date_to: f.dateTo });
  return useQuery({ queryKey: ["reports", "dashboard", q], queryFn: () => api<Dashboard>(`/reports/dashboard${q}`), placeholderData: keepPreviousData });
}

/** Директор без выбранной точки ("all") не передаёт location_id — сервер берёт первую по имени. */
export function useLocationSummary(f: { locationId: string; period: SummaryPeriod | "custom"; dateFrom?: string; dateTo?: string; enabled?: boolean }) {
  const q = qs({ location_id: locParam(f.locationId), period: f.period, date_from: f.dateFrom, date_to: f.dateTo });
  return useQuery({
    queryKey: ["reports", "summary", q],
    queryFn: () => api<LocationSummary>(`/reports/location-summary${q}`),
    enabled: f.enabled ?? true,
    placeholderData: keepPreviousData,
  });
}

/** Сводка дня: ошибка не должна ломать «Сегодня» — вызывающий показывает блок только при данных. */
export function useDashboardToday(locationId: string) {
  const q = qs({ location_id: locParam(locationId) });
  return useQuery({
    queryKey: ["reports", "today", q],
    queryFn: () => api<DashboardToday>(`/dashboard/today${q}`),
    meta: { silent: true },
    enabled: !!locationId,
    refetchInterval: 60_000,
  });
}

/* ---------- Отчёты (D-02) ---------- */

export interface ReportParams {
  id: ReportId;
  locationId: string;
  department: "" | Department;
  dateFrom: string;
  dateTo: string;
  groupBy: string;
}

function reportQuery(p: Omit<ReportParams, "id">): string {
  return qs({ location_id: locParam(p.locationId), department: p.department, date_from: p.dateFrom, date_to: p.dateTo, group_by: p.groupBy });
}

export function useReport(p: ReportParams) {
  const q = reportQuery(p);
  return useQuery({ queryKey: ["reports", "report", p.id, q], queryFn: () => api<Report>(`/reports/${enc(p.id)}${q}`), placeholderData: keepPreviousData });
}

export const reportExportPath = (p: ReportParams, format: string) =>
  `/reports/${enc(p.id)}/export${qs({ location_id: locParam(p.locationId), department: p.department, date_from: p.dateFrom, date_to: p.dateTo, group_by: p.groupBy, format })}`;

/* ---------- Зарплата (D-03) ---------- */

export function usePayroll(f: { month: string; locationId: string }) {
  const q = qs({ month: f.month, location_id: locParam(f.locationId) });
  return useQuery({ queryKey: ["payroll", "sheet", q], queryFn: () => api<PayrollSheet>(`/payroll${q}`), placeholderData: keepPreviousData });
}

export function usePayrollDetail(userId: string, month: string, enabled: boolean) {
  const q = qs({ month });
  return useQuery({
    queryKey: ["payroll", "detail", userId, month],
    queryFn: () => api<PayrollDetail>(`/payroll/${enc(userId)}${q}`),
    enabled: enabled && !!userId,
  });
}

export const payrollExportPath = (f: { month: string; locationId: string }, format: string) =>
  `/payroll/export${qs({ month: f.month, location_id: locParam(f.locationId), format })}`;

export function usePayrollSchemes(userId: string, enabled = true) {
  return useQuery({
    queryKey: ["payroll", "schemes", userId],
    queryFn: () => api<PayrollScheme[]>(`/payroll/schemes${qs({ user_id: userId })}`),
    enabled: enabled && !!userId,
  });
}

export interface SchemeInput {
  user_id: string;
  scheme_type: PayrollSchemeType;
  percent?: string;
  norm_hour_rate?: string;
  fixed_monthly?: string;
  department?: Department | null;
  valid_from: string;
}

export function useCreateScheme() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: SchemeInput) => api<PayrollScheme>("/payroll/schemes", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payroll"] }),
  });
}

export function useEndScheme() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; valid_to: string }) => api<PayrollScheme>(`/payroll/schemes/${enc(v.id)}`, { method: "PATCH", body: { valid_to: v.valid_to } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payroll"] }),
  });
}

export function useDeleteScheme() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (id: string) => api<void>(`/payroll/schemes/${enc(id)}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payroll"] }),
  });
}

export interface AdjustmentInput { user_id: string; month: string; amount: string; reason: string }

export function useCreateAdjustment() {
  const qc = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (b: AdjustmentInput) => api<PayrollAdjustment>("/payroll/adjustments", { body: b }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payroll"] }),
  });
}

/* ---------- Заработок механика (M-07) ---------- */

export function useMyEarnings(month: string) {
  const q = qs({ month });
  return useQuery({ queryKey: ["earnings", q], queryFn: () => api<MyEarnings>(`/me/earnings${q}`), placeholderData: keepPreviousData });
}

/* ---------- Тепловая карта ---------- */

export function useActivityHeatmap(userId: string, from: string, to: string) {
  const q = qs({ from, to });
  return useQuery({
    queryKey: ["activity", "heatmap", userId, from, to],
    queryFn: () => api<ActivityHeatmapData>(`/users/${enc(userId)}/activity-heatmap${q}`),
    enabled: !!userId && !!from && !!to,
    retry: false,
  });
}

export function useActivityDetails(userId: string, dateFrom: string, dateTo: string, enabled = true) {
  const q = qs({ date_from: dateFrom, date_to: dateTo });
  return useQuery({
    queryKey: ["activity", "details", userId, dateFrom, dateTo],
    queryFn: () => api<ActivityDetails>(`/users/${enc(userId)}/activity-details${q}`),
    enabled: enabled && !!userId && !!dateFrom && !!dateTo,
    retry: false,
  });
}
