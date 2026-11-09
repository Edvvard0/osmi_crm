/** Сообщения модуля 11: подхватываются реестром shared/api/errors.ts автоматически. Новых кодов ошибок модуль не вводит. */

export const errorMessages: Record<string, string> = {};

export const fieldMessages: Record<string, string> = {};

export const fieldFallbacks: Record<string, string> = {
  date_from: "Недопустимая дата начала",
  date_to: "Период — не более 366 суток, конец не раньше начала",
  offset: "Слишком глубокая выборка. Сузьте фильтры",
  action: "Недопустимое действие",
  entity_type: "Недопустимый тип объекта",
  user_id: "Недопустимый сотрудник",
  location_id: "Недопустимая точка",
  discount_alert_percent: "Порог скидки: от 1 до 100 %",
  daily_summary_time: "Время сводки: от 00:00 до 23:59",
  session_retention_days: "Срок хранения сессий: от 7 до 365 дней",
  heatmap_thresholds: "Пороги должны строго возрастать и укладываться в допустимые диапазоны",
};
