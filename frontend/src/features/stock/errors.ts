/** Сообщения модуля 8 «Склад»: подхватываются реестром shared/api/errors.ts автоматически. */

export const errorMessages: Record<string, string> = {
  insufficient_stock: "На складе недостаточно остатка",
  stock_changed: "Остатки изменились, обновите страницу",
  already_reversed: "Это движение уже сторнировано",
};

export const fieldMessages: Record<string, string> = {};

export const fieldFallbacks: Record<string, string> = {
  items: "Проверьте позиции: запчасть должна быть активной, без повторов, количество — число больше 0, до трёх знаков после запятой",
  supplier: "Поставщик: до 200 символов",
  document_number: "Номер накладной: до 50 символов",
  reason: "Причина: от 3 до 500 символов",
  min_quantity: "Минимум: число не меньше 0, до трёх знаков после запятой",
  from_location_id: "Выберите исходную точку",
  to_location_id: "Выберите другую активную точку",
  date_from: "Недопустимая дата начала",
  date_to: "Период: не более 366 суток",
};
