type Role = "mechanic" | "manager" | "director";

// «Обзор» директора — главная (/), «Сегодня» менеджера — модуль 5; здесь отчёты, зарплата и заработок.
export const nav: Array<{ to: string; label: string; roles: Role[]; order: number }> = [
  { to: "/earnings", label: "Заработок", roles: ["mechanic"], order: 25 },
  { to: "/location-report", label: "Отчёт точки", roles: ["manager"], order: 55 },
  { to: "/reports", label: "Отчёты", roles: ["director"], order: 60 },
  { to: "/payroll", label: "Зарплата", roles: ["director"], order: 65 },
];
