export type Role = "mechanic" | "manager" | "director";

export const ROLE_LABELS: Record<Role, string> = {
  mechanic: "Механик",
  manager: "Менеджер",
  director: "Руководитель",
};

export interface User {
  id: string;
  login: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  location_ids: string[];
  created_at: string;
}

export interface CrmLocation {
  id: string;
  name: string;
  address: string;
  phone: string | null;
  is_active: boolean;
  code: string;
  /** IANA-пояс точки, например Europe/Moscow. */
  timezone: string;
  /** Рабочие часы точки: "HH:MM". */
  work_start: string;
  work_end: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface Session {
  access_token: string;
  expires_in: number;
  user: User;
}

export type ClientType = "person" | "company";
export type ClientSource = "walk_in" | "referral" | "online" | "ads" | "repeat" | "other";

export const SOURCE_LABELS: Record<ClientSource, string> = {
  walk_in: "Пришёл сам",
  referral: "Рекомендация",
  online: "Интернет",
  ads: "Реклама",
  repeat: "Повторное обращение",
  other: "Другое",
};

export interface Client {
  id: string;
  client_type: ClientType;
  full_name: string;
  company_name: string | null;
  inn: string | null;
  phone: string;
  phone_extra: string | null;
  email: string | null;
  source: ClientSource | null;
  discount_percent: number;
  notes: string | null;
  vehicles_count: number;
  created_at: string;
  archived_at: string | null;
}

export interface Vehicle {
  id: string;
  client_id: string;
  make: string;
  model: string;
  year: number | null;
  vin: string | null;
  plate_number: string | null;
  color: string | null;
  mileage: number | null;
  notes: string | null;
  created_at: string;
  archived_at: string | null;
}

export type ClientDetail = Client & { vehicles: Vehicle[] };
export type VehicleDetail = Vehicle & { client: { id: string; full_name: string; phone: string } };

export interface SearchHit {
  type: "client" | "vehicle";
  id: string;
  title: string;
  subtitle: string;
  client_id: string;
}

/* ===== Модуль 3: каталог, цены, посты, запчасти. Деньги и часы — строки-десятичные. ===== */

export type Department = "service" | "detailing";
export const DEPARTMENT_LABELS: Record<Department, string> = { service: "Сервис", detailing: "Детейлинг" };

export type ServiceUnit = "pcs" | "hour" | "set" | "sqm";
export const SERVICE_UNIT_LABELS: Record<ServiceUnit, string> = { pcs: "шт", hour: "час", set: "компл.", sqm: "м²" };

export interface Category {
  id: string;
  name: string;
  department: Department;
  sort_order: number;
  is_active: boolean;
}

export interface Service {
  id: string;
  category_id: string;
  code: string;
  name: string;
  description: string | null;
  department: Department;
  unit: ServiceUnit;
  base_price: string;
  norm_hours: string | null;
  duration_minutes: number;
  is_active: boolean;
  /** Эффективная цена для точки из параметра location_id (иначе base_price). */
  price: string;
}

export interface ServicePrice {
  service_id: string;
  location_id: string;
  price: string;
  updated_at: string;
}

export type PostType = "lift" | "diagnostics" | "detailing_box" | "wash" | "other";
export const POST_TYPE_LABELS: Record<PostType, string> = {
  lift: "Подъёмник",
  diagnostics: "Диагностика",
  detailing_box: "Бокс детейлинга",
  wash: "Мойка",
  other: "Другое",
};

export interface Post {
  id: string;
  location_id: string;
  name: string;
  post_type: PostType;
  department: Department;
  sort_order: number;
  is_active: boolean;
}

export type PartUnit = "pcs" | "l" | "ml" | "kg" | "g" | "m" | "set";
export const PART_UNIT_LABELS: Record<PartUnit, string> = { pcs: "шт", l: "л", ml: "мл", kg: "кг", g: "г", m: "м", set: "компл." };
export type PartDepartment = Department | "both";
export const PART_DEPARTMENT_LABELS: Record<PartDepartment, string> = { service: "Сервис", detailing: "Детейлинг", both: "Оба отдела" };

export interface Part {
  id: string;
  sku: string;
  name: string;
  brand: string | null;
  barcode: string | null;
  unit: PartUnit;
  department: PartDepartment;
  sale_price: string;
  is_active: boolean;
}

/* ===== Модуль 4: записи (календарь). Время — ISO 8601 со смещением пояса точки. ===== */

export type AppointmentStatus = "scheduled" | "confirmed" | "arrived" | "no_show" | "cancelled";
export const APPOINTMENT_STATUS_LABELS: Record<AppointmentStatus, string> = {
  scheduled: "Запланирована",
  confirmed: "Подтверждена",
  arrived: "Клиент приехал",
  no_show: "Не приехал",
  cancelled: "Отменена",
};

export interface Appointment {
  id: string;
  location_id: string;
  client_id: string;
  vehicle_id: string;
  post_id: string | null;
  department: Department;
  start_at: string;
  end_at: string;
  status: AppointmentStatus;
  comment: string | null;
  service_ids: string[];
  services: { id: string; name: string }[];
  client: { id: string; full_name: string; phone: string };
  vehicle: { id: string; make: string; model: string; plate_number: string | null };
  work_order_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}
