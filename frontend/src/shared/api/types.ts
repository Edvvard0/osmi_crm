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
