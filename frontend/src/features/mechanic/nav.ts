type Role = "mechanic" | "manager" | "director";

// «Задачи» (/) и «Настройки» (/settings) уже есть в Layout под общими названиями; «Заработок» добавит модуль 10.
export const nav: Array<{ to: string; label: string; roles: Role[]; order: number }> = [
  { to: "/requests", label: "Заявки", roles: ["mechanic"], order: 20 },
  { to: "/part-requests", label: "Заявки механиков", roles: ["manager", "director"], order: 45 },
];
